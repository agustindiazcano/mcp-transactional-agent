"""Tests for the promptfoo judge provider's pure helpers (evals/promptfoo)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "evals" / "promptfoo"))

import judge_provider


@pytest.mark.parametrize(
    ("section", "rule"),
    [
        ("Standard Refund Window", "within 30 days"),
        ("Extended Warranty Exceptions", "12 or 24 months"),
        ("Refund Amount Limits and Fraud Flags", "exceeding $5000"),
        ("Refund Method", "original payment method"),
        ("Non-Refundable Items", "gift cards"),
    ],
)
def test_policy_chunk_holds_the_sections_rules_not_just_its_heading(section: str, rule: str) -> None:
    """The chunker can leave a heading at the end of one chunk and its body in
    the next; a case must get the chunk with the rules (found in the first run:
    the $5000 cases got a chunk with the heading only)."""
    assert rule in judge_provider.policy_chunk(section)


def test_judge_inputs_mirror_the_worker() -> None:
    args, context = judge_provider.judge_inputs(
        {
            "request_id": "eval-1",
            "user_id": "u",
            "claim_text": "broken",
            "amount": 10.0,
            "expected": "APPROVE",
            "policy_section": "Refund Method",
        }
    )

    assert args == {"request_id": "eval-1", "user_id": "u", "claim_text": "broken", "amount": 10.0}
    assert context["request_id"] == "eval-1"
    assert "original payment method" in context["retrieved_policy"]
