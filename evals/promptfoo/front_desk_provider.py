"""Promptfoo provider: runs the Front-Desk proposer on one labeled claim, the
way production does.

It reuses production code instead of copying it, so the eval grades what
runs:
- the messages come from `build_front_desk_messages()` (system prompt +
  untrusted-data fencing),
- the reply is parsed by `parse_proposal()` and validated by `ClaimProposal`,
- the model comes from `get_llm()`, with the provider and model from the
  promptfoo provider `config` (one entry per model in
  front_desk_promptfooconfig.yaml).

`worker.py` only ever reads `proposal.intent` (intent-gate-only design, see
PENDING.md Phase 1.E) -- the eval scores intent classification, not argument
extraction accuracy.

A reply that can't be parsed, or that parses but fails `ClaimProposal`'s own
validation, counts as `clarify`, exactly as production's `_propose()` does
(fail closed, never surface a half-formed or guessed refund). A provider or
network error is reported to promptfoo as an error instead, so it isn't
scored as a proposal.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:  # promptfoo runs this file from its own worker
    sys.path.insert(0, str(REPO_ROOT))

from src.agents.front_desk import build_front_desk_messages, parse_proposal
from src.agents.llm_factory import get_llm
from src.agents.proposal import ClaimProposal
from src.agents.token_usage import extract_usage


def front_desk_messages(case_vars: dict[str, Any]) -> list[BaseMessage]:
    """The messages a case sends, shaped like the worker's `propose_action()`."""
    return build_front_desk_messages(
        case_vars["claim_text"], rejection_feedback=case_vars.get("rejection_feedback")
    )


async def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Promptfoo entry point. `prompt` is unused: the messages are production's."""
    config = options.get("config", {})
    messages = front_desk_messages(context["vars"])

    started = time.perf_counter()
    try:
        llm = get_llm(provider=config["provider"], temperature=0.0, model_name=config.get("model"))
        response = await llm.ainvoke(messages)
    except Exception as e:  # noqa: BLE001 -- reported to promptfoo as an error, not a proposal
        return {"error": f"{type(e).__name__}: {e}"}
    latency_ms = round((time.perf_counter() - started) * 1000)

    try:
        raw = parse_proposal(response.content)
        proposal = ClaimProposal(**raw)
    except (ValueError, TypeError, json.JSONDecodeError, ValidationError) as e:
        proposal = ClaimProposal(
            intent="clarify", reason=f"System Guardrail Error: {e}"
        )

    usage: dict[str, Any] = dict(extract_usage(response) or {})
    return {
        "output": proposal.model_dump_json(),
        "latencyMs": latency_ms,
        "tokenUsage": {
            "prompt": usage.get("input_tokens", 0),
            "completion": usage.get("output_tokens", 0),
            "total": usage.get("total_tokens", 0),
            "numRequests": 1,
        },
    }
