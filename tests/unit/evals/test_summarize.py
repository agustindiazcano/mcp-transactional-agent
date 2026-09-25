"""Tests for the eval summary report (evals/promptfoo/summarize.py)."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "evals" / "promptfoo"))

import summarize


def row(
    provider: str,
    case: str,
    expected: str,
    verdict: str | None,
    latency: int = 1000,
    prompt_tokens: int = 100,
    completion_tokens: int = 10,
) -> dict[str, Any]:
    """One promptfoo result row, shaped like `promptfoo eval -o results.json`."""
    response: dict[str, Any] | None = None
    if verdict is not None:
        response = {
            "output": json.dumps({"verdict": verdict, "reason": "r"}),
            "tokenUsage": {"prompt": prompt_tokens, "completion": completion_tokens},
        }
    return {
        "provider": {"id": "file://judge_provider.py", "label": provider},
        "vars": {"request_id": case, "expected": expected},
        "response": response,
        "latencyMs": latency,
    }


def test_counts_false_approvals_and_false_rejections() -> None:
    rows = [
        row("m", "a", "APPROVE", "APPROVE"),
        row("m", "b", "APPROVE", "REJECT"),  # false rejection
        row("m", "c", "REJECT", "APPROVE"),  # false approval: the dangerous one
        row("m", "d", "REJECT", "REJECT"),
    ]

    (s,) = summarize.summarize(rows, prices={})

    assert (s.runs, s.correct, s.false_approvals, s.false_rejections) == (4, 2, 1, 1)
    assert s.accuracy == 0.5
    assert s.false_approval_rate == 0.5  # 1 of the 2 REJECT-labeled runs


def test_stability_is_the_share_of_cases_with_one_verdict_across_repeats() -> None:
    rows = [
        row("m", "a", "APPROVE", "APPROVE"),
        row("m", "a", "APPROVE", "APPROVE"),
        row("m", "b", "REJECT", "REJECT"),
        row("m", "b", "REJECT", "APPROVE"),  # flipped between repeats
    ]

    (s,) = summarize.summarize(rows, prices={})

    assert s.cases == 2
    assert s.stability == 0.5


def test_errors_are_counted_but_not_scored_as_verdicts() -> None:
    rows = [row("m", "a", "REJECT", None), row("m", "b", "REJECT", "REJECT")]

    (s,) = summarize.summarize(rows, prices={})

    assert s.errors == 1
    assert s.runs == 1
    assert s.false_approvals == 0


def test_cost_uses_the_price_per_million_tokens_of_the_model() -> None:
    rows = [row("m", "a", "APPROVE", "APPROVE", prompt_tokens=1_000_000, completion_tokens=500_000)]
    prices = {"m": summarize.Price(input_per_million=0.10, output_per_million=0.40)}

    (s,) = summarize.summarize(rows, prices=prices)

    assert s.cost_per_judgment == pytest.approx(0.10 + 0.20)


def test_one_summary_per_provider_in_first_seen_order() -> None:
    rows = [row("b", "x", "APPROVE", "APPROVE"), row("a", "x", "APPROVE", "APPROVE")]

    assert [s.provider for s in summarize.summarize(rows, prices={})] == ["b", "a"]


def test_markdown_table_has_a_row_per_provider_and_no_cost_when_unpriced() -> None:
    rows = [row("m", "a", "APPROVE", "APPROVE", latency=1234)]

    table = summarize.to_markdown(summarize.summarize(rows, prices={}))

    assert table.splitlines()[0].startswith("| Model |")
    assert "| m | 100% |" in table
    assert "1.2 s" in table
    assert "n/a" in table
