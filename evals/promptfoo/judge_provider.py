"""Promptfoo provider: runs ONE judge on a labeled claim, the way production does.

It reuses production code instead of copying it, so the eval grades what runs:
- the messages come from `build_judge_messages()` (system prompt + fencing),
- the reply is parsed by `parse_verdict()`,
- the model comes from `get_llm()`, with the provider and model from the
  promptfoo provider `config` (one entry per model in promptfooconfig.yaml),
- the policy text is the real chunk ingestion stores (`chunk_markdown()` over
  docs/policies/refund_policy.md), picked by the case's `policy_section`, so the
  judge gets what a correct retrieval returns.

A reply that can't be parsed counts as REJECT, exactly as in production
(`_invoke_judge` fails closed). A provider/network error is reported to
promptfoo as an error instead, so it isn't scored as a judge decision.
"""

import json
import sys
import time
from functools import cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:  # promptfoo runs this file from its own worker
    sys.path.insert(0, str(REPO_ROOT))

from src.agents.judge import build_judge_messages, parse_verdict
from src.agents.llm_factory import get_llm
from src.agents.token_usage import extract_usage
from src.core.services.chunking import chunk_markdown

POLICY_PATH = REPO_ROOT / "docs" / "policies" / "refund_policy.md"

# The claim fields the worker passes to the judges as the proposal's arguments.
CLAIM_FIELDS = ("request_id", "user_id", "claim_text", "order_id", "amount", "currency")


@cache
def policy_chunks() -> tuple[str, ...]:
    """The refund policy split exactly as ingestion splits it."""
    return tuple(chunk_markdown(POLICY_PATH.read_text(encoding="utf-8")))


def policy_chunk(section: str) -> str:
    """The chunk holding the rules of `## <section>`, as a correct retrieval returns it.

    Matched on the section's first paragraph, not its heading: the chunker can
    leave a heading at the end of one chunk and its rules in the next.
    """
    paragraphs = [p.strip() for p in POLICY_PATH.read_text(encoding="utf-8").split("\n\n")]
    heading = f"## {section}"
    if heading not in paragraphs:
        raise KeyError(f"The policy has no {heading!r} section")
    first_rule = paragraphs[paragraphs.index(heading) + 1]
    for chunk in policy_chunks():
        if first_rule in chunk:
            return chunk
    raise KeyError(f"No policy chunk holds the rules of {heading!r}")


def judge_inputs(case_vars: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(action_args, context) for a case, shaped like the worker's."""
    args = {field: case_vars[field] for field in CLAIM_FIELDS if case_vars.get(field) is not None}
    context: dict[str, Any] = {"request_id": case_vars.get("request_id")}
    section = case_vars.get("policy_section")
    if section:
        context["retrieved_policy"] = policy_chunk(section)
    return args, context


async def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Promptfoo entry point. `prompt` is unused: the messages are production's."""
    config = options.get("config", {})
    args, judge_context = judge_inputs(context["vars"])
    messages = build_judge_messages("execute_refund", args, judge_context)

    started = time.perf_counter()
    try:
        llm = get_llm(provider=config["provider"], temperature=0.0, model_name=config.get("model"))
        response = await llm.ainvoke(messages)
    except Exception as e:  # noqa: BLE001 -- reported to promptfoo as an error, not a verdict
        return {"error": f"{type(e).__name__}: {e}"}
    latency_ms = round((time.perf_counter() - started) * 1000)

    try:
        verdict = parse_verdict(response.content)
    except (ValueError, json.JSONDecodeError) as e:
        verdict = {"verdict": "REJECT", "reason": f"System Guardrail Error: {e}"}

    usage: dict[str, Any] = dict(extract_usage(response) or {})
    return {
        "output": json.dumps(verdict),
        "latencyMs": latency_ms,
        "tokenUsage": {
            "prompt": usage.get("input_tokens", 0),
            "completion": usage.get("output_tokens", 0),
            "total": usage.get("total_tokens", 0),
            "numRequests": 1,
        },
    }
