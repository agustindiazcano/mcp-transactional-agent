"""Turn a promptfoo results file into the Front-Desk proposer benchmark table.

Usage (from the repo root):
    python evals/promptfoo/summarize_front_desk.py results.json
        [--prices evals/promptfoo/prices.json] [--relabel CASE_ID=LABEL ...]
        [--save-compact compact.json]

Mirrors summarize.py, adapted for the Front-Desk's 3-way intent label
(refund / clarify / out_of_scope) instead of the judges' binary
APPROVE/REJECT -- `worker.py` only ever reads `proposal.intent`
(intent-gate-only design), so that's what this eval scores.

Per model it reports accuracy, false refunds (a clarify/out_of_scope-labeled
claim the proposer classified as refund: the dangerous error -- it burns an
evidence check and a judge call the claim never earned), missed refunds (the
reverse: safe, but bad UX), stability, latency, tokens and cost per
proposal. Pure functions plus a thin CLI, so the numbers are unit-tested.
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LABELS = ("refund", "clarify", "out_of_scope")

# The fields of a promptfoo response the report reads.
_COMPACT_RESPONSE_KEYS = ("output", "tokenUsage")


@dataclass(frozen=True)
class Price:
    """USD per million tokens. Thinking tokens are billed as output."""

    input_per_million: float
    output_per_million: float


@dataclass(frozen=True)
class ModelSummary:
    """One model's results over every case and repeat."""

    provider: str
    cases: int
    runs: int
    errors: int
    correct: int
    false_refunds: int
    missed_refunds: int
    refund_runs: int
    non_refund_runs: int
    stability: float
    median_latency_ms: float
    p95_latency_ms: float
    mean_input_tokens: float
    mean_output_tokens: float
    cost_per_judgment: float | None

    @property
    def accuracy(self) -> float:
        return self.correct / self.runs if self.runs else 0.0

    @property
    def false_refund_rate(self) -> float:
        return self.false_refunds / self.non_refund_runs if self.non_refund_runs else 0.0

    @property
    def missed_refund_rate(self) -> float:
        return self.missed_refunds / self.refund_runs if self.refund_runs else 0.0


def _intent(result: dict[str, Any]) -> str | None:
    """The proposer's classified intent, or None when the call errored."""
    response = result.get("response") or {}
    output = response.get("output")
    if not output:
        return None
    try:
        return str(json.loads(output)["intent"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def compact(result: dict[str, Any]) -> dict[str, Any]:
    """A result row reduced to what the report reads (drops the prompt, etc.)."""
    response = result.get("response")
    return {
        "provider": {"label": result["provider"].get("label") or result["provider"]["id"]},
        "description": (result.get("testCase") or {}).get("description"),
        "vars": {k: result["vars"][k] for k in ("request_id", "expected_intent")},
        "response": (
            {k: response[k] for k in _COMPACT_RESPONSE_KEYS if k in response} if response else None
        ),
        "latencyMs": result.get("latencyMs"),
    }


def parse_relabel(pairs: list[str]) -> dict[str, str]:
    """{case id: label} from CLI pairs like "eval-fd-clarify-03=out_of_scope"."""
    relabel = {}
    for pair in pairs:
        case_id, _, label = pair.partition("=")
        if label not in LABELS:
            raise ValueError(f"{pair!r}: the label must be one of {LABELS}")
        relabel[case_id] = label
    return relabel


def summarize(
    results: list[dict[str, Any]],
    prices: dict[str, Price],
    relabel: dict[str, str] | None = None,
) -> list[ModelSummary]:
    """One ModelSummary per provider label, in first-seen order."""
    relabels = relabel or {}

    def expected(result: dict[str, Any]) -> str:
        return str(relabels.get(result["vars"]["request_id"], result["vars"]["expected_intent"]))

    by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_provider[result["provider"].get("label") or result["provider"]["id"]].append(result)

    summaries = []
    for provider, rows in by_provider.items():
        scored = [(r, v) for r in rows if (v := _intent(r)) is not None]
        intents_per_case: dict[str, set[str]] = defaultdict(set)
        for r, v in scored:
            intents_per_case[r["vars"]["request_id"]].add(v)

        input_tokens = [(r["response"].get("tokenUsage") or {}).get("prompt", 0) for r, _ in scored]
        output_tokens = [(r["response"].get("tokenUsage") or {}).get("completion", 0) for r, _ in scored]
        latencies = [float(r.get("latencyMs") or 0) for r, _ in scored] or [0.0]
        mean_in = statistics.fmean(input_tokens) if input_tokens else 0.0
        mean_out = statistics.fmean(output_tokens) if output_tokens else 0.0
        price = prices.get(provider)

        summaries.append(
            ModelSummary(
                provider=provider,
                cases=len(intents_per_case),
                runs=len(scored),
                errors=len(rows) - len(scored),
                correct=sum(v == expected(r) for r, v in scored),
                false_refunds=sum(
                    expected(r) != "refund" and v == "refund" for r, v in scored
                ),
                missed_refunds=sum(
                    expected(r) == "refund" and v != "refund" for r, v in scored
                ),
                refund_runs=sum(expected(r) == "refund" for r, _ in scored),
                non_refund_runs=sum(expected(r) != "refund" for r, _ in scored),
                stability=(
                    sum(len(v) == 1 for v in intents_per_case.values()) / len(intents_per_case)
                    if intents_per_case
                    else 0.0
                ),
                median_latency_ms=statistics.median(latencies),
                p95_latency_ms=_percentile(latencies, 0.95),
                mean_input_tokens=mean_in,
                mean_output_tokens=mean_out,
                cost_per_judgment=(
                    (mean_in * price.input_per_million + mean_out * price.output_per_million) / 1e6
                    if price
                    else None
                ),
            )
        )
    return summaries


def to_markdown(summaries: list[ModelSummary]) -> str:
    """The benchmark table, one row per model."""
    lines = [
        (
            "| Model | Accuracy | False refunds | Missed refunds | Stable cases "
            "| Median latency | P95 latency | Tokens in / out | Cost per judgment |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        cost = f"${s.cost_per_judgment:.6f}" if s.cost_per_judgment is not None else "n/a"
        lines.append(
            f"| {s.provider} | {s.accuracy:.0%} | {s.false_refunds}/{s.non_refund_runs} "
            f"| {s.missed_refunds}/{s.refund_runs} | {s.stability:.0%} of {s.cases} "
            f"| {s.median_latency_ms / 1000:.1f} s | {s.p95_latency_ms / 1000:.1f} s "
            f"| {s.mean_input_tokens:.0f} / {s.mean_output_tokens:.0f} | {cost} |"
        )
    return "\n".join(lines)


def load_prices(path: Path) -> dict[str, Price]:
    """Prices keyed by provider label, from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        label: Price(float(p["input_per_million"]), float(p["output_per_million"]))
        for label, p in (data.get("models") or {}).items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path, help="promptfoo eval -o <file>.json")
    parser.add_argument("--prices", type=Path, help="JSON of USD per million tokens per model")
    parser.add_argument("--relabel", action="append", default=[], metavar="CASE_ID=LABEL")
    parser.add_argument("--save-compact", type=Path, help="write the compact results here")
    args = parser.parse_args(argv)

    data = json.loads(args.results.read_text(encoding="utf-8"))
    # promptfoo's own file nests the rows; a compact file is a list under "results".
    rows = data["results"]["results"] if isinstance(data["results"], dict) else data["results"]
    if args.save_compact:
        args.save_compact.write_text(
            json.dumps({"results": [compact(r) for r in rows]}, indent=1), encoding="utf-8"
        )
    prices = load_prices(args.prices) if args.prices else {}
    summaries = summarize(rows, prices, parse_relabel(args.relabel))
    sys.stdout.write(to_markdown(summaries) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
