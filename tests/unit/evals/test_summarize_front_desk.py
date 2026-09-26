"""Tests for the Front-Desk eval summary report (evals/promptfoo/summarize_front_desk.py).

Mirrors test_summarize.py, adapted for the Front-Desk's 3-way intent label
(refund / clarify / out_of_scope) instead of the judges' binary
APPROVE/REJECT. The dangerous direction here is a `false_refund`: a claim
labeled clarify/out_of_scope that the proposer classified as refund -- it
burns an evidence check and a judge call the claim never earned, the
Front-Desk analog of the judges' false approval.
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "evals" / "promptfoo"))

import summarize_front_desk as sfd


def row(
    provider: str,
    case: str,
    expected_intent: str,
    intent: str | None,
    latency: int = 1000,
    prompt_tokens: int = 100,
    completion_tokens: int = 10,
) -> dict[str, Any]:
    """One promptfoo result row, shaped like `promptfoo eval -o results.json`."""
    response: dict[str, Any] | None = None
    if intent is not None:
        response = {
            "output": json.dumps({"intent": intent, "reason": "r"}),
            "tokenUsage": {"prompt": prompt_tokens, "completion": completion_tokens},
        }
    return {
        "provider": {"id": "file://front_desk_provider.py", "label": provider},
        "vars": {"request_id": case, "expected_intent": expected_intent},
        "response": response,
        "latencyMs": latency,
    }


def test_counts_false_refunds_and_missed_refunds() -> None:
    rows = [
        row("m", "a", "refund", "refund"),
        row("m", "b", "refund", "clarify"),  # missed refund
        row("m", "c", "clarify", "refund"),  # false refund: the dangerous one
        row("m", "d", "out_of_scope", "out_of_scope"),
    ]

    (s,) = sfd.summarize(rows, prices={})

    assert (s.runs, s.correct, s.false_refunds, s.missed_refunds) == (4, 2, 1, 1)
    assert s.accuracy == 0.5
    assert s.false_refund_rate == 0.5  # 1 of the 2 non-refund-labeled runs
    assert s.missed_refund_rate == 0.5  # 1 of the 2 refund-labeled runs


def test_stability_is_the_share_of_cases_with_one_intent_across_repeats() -> None:
    rows = [
        row("m", "a", "refund", "refund"),
        row("m", "a", "refund", "refund"),
        row("m", "b", "clarify", "clarify"),
        row("m", "b", "clarify", "refund"),  # flipped between repeats
    ]

    (s,) = sfd.summarize(rows, prices={})

    assert s.cases == 2
    assert s.stability == 0.5


def test_errors_are_counted_but_not_scored() -> None:
    rows = [row("m", "a", "clarify", None), row("m", "b", "clarify", "clarify")]

    (s,) = sfd.summarize(rows, prices={})

    assert s.errors == 1
    assert s.runs == 1
    assert s.false_refunds == 0


def test_cost_uses_the_price_per_million_tokens_of_the_model() -> None:
    rows = [row("m", "a", "refund", "refund", prompt_tokens=1_000_000, completion_tokens=500_000)]
    prices = {"m": sfd.Price(input_per_million=0.10, output_per_million=0.40)}

    (s,) = sfd.summarize(rows, prices=prices)

    assert s.cost_per_judgment == pytest.approx(0.10 + 0.20)


def test_one_summary_per_provider_in_first_seen_order() -> None:
    rows = [row("b", "x", "refund", "refund"), row("a", "x", "refund", "refund")]

    assert [s.provider for s in sfd.summarize(rows, prices={})] == ["b", "a"]


def test_markdown_table_has_a_row_per_provider_and_no_cost_when_unpriced() -> None:
    rows = [row("m", "a", "refund", "refund", latency=1234)]

    table = sfd.to_markdown(sfd.summarize(rows, prices={}))

    assert table.splitlines()[0].startswith("| Model |")
    assert "| m | 100% |" in table
    assert "1.2 s" in table
    assert "n/a" in table


def test_relabel_rescores_a_case_without_editing_the_raw_results() -> None:
    rows = [row("m", "a", "refund", "clarify")]

    (s,) = sfd.summarize(rows, prices={}, relabel={"a": "clarify"})

    assert (s.correct, s.missed_refunds) == (1, 0)
    assert rows[0]["vars"]["expected_intent"] == "refund"


def test_parse_relabel_reads_case_equals_label() -> None:
    assert sfd.parse_relabel(["eval-1=out_of_scope", "eval-2=refund"]) == {
        "eval-1": "out_of_scope",
        "eval-2": "refund",
    }
    with pytest.raises(ValueError):
        sfd.parse_relabel(["eval-1=maybe"])


def test_compact_keeps_what_the_report_needs_and_scores_the_same() -> None:
    raw = [row("m", "a", "clarify", "refund"), row("m", "b", "refund", "refund")]
    raw[0]["prompt"] = {"raw": "a long prompt the report never reads"}

    compacted = [sfd.compact(r) for r in raw]

    assert "prompt" not in compacted[0]
    assert sfd.summarize(compacted, prices={}) == sfd.summarize(raw, prices={})
