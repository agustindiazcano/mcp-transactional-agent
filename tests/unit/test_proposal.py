"""Unit tests for the Front-Desk's proposal schema (src/agents/proposal.py).

Phase 1.E (CLAUDE.md Section 5a-iv): the primary agent no longer decides
anything -- it only proposes a structured intent, which the Back-Office
re-validates server-side before it ever reaches the Double Judge. This
schema is that contract, so it is exercised the same way the gateway's own
`ClaimRequest` is (tests/unit/test_api_schemas.py): every field the LLM
could hallucinate or omit is checked here, independent of any real LLM call.
"""
import pytest
from pydantic import ValidationError
from src.agents.proposal import ClaimProposal

from src.core.config import settings
from src.core.currency import Currency


def test_refund_proposal_accepts_full_payload() -> None:
    proposal = ClaimProposal(
        intent="refund",
        order_id="ord-42",
        amount=49.99,
        currency="EUR",
        reason="The customer says the item arrived damaged.",
    )

    assert proposal.intent == "refund"
    assert proposal.order_id == "ord-42"
    assert proposal.amount == 49.99
    assert proposal.currency is Currency.EUR


def test_refund_proposal_requires_order_id() -> None:
    with pytest.raises(ValidationError):
        ClaimProposal(
            intent="refund", amount=49.99, currency="EUR", reason="Damaged item."
        )


def test_refund_proposal_requires_amount() -> None:
    with pytest.raises(ValidationError):
        ClaimProposal(
            intent="refund", order_id="ord-42", currency="EUR", reason="Damaged item."
        )


def test_refund_proposal_requires_currency() -> None:
    with pytest.raises(ValidationError):
        ClaimProposal(
            intent="refund", order_id="ord-42", amount=49.99, reason="Damaged item."
        )


def test_refund_proposal_rejects_amount_above_refund_max() -> None:
    with pytest.raises(ValidationError):
        ClaimProposal(
            intent="refund",
            order_id="ord-42",
            amount=settings.REFUND_MAX_AMOUNT + 1,
            currency="USD",
            reason="Large refund.",
        )


def test_refund_proposal_rejects_non_positive_amount() -> None:
    with pytest.raises(ValidationError):
        ClaimProposal(
            intent="refund", order_id="ord-42", amount=0, currency="USD", reason="Zero."
        )


def test_refund_proposal_rejects_unknown_currency() -> None:
    with pytest.raises(ValidationError):
        ClaimProposal(
            intent="refund", order_id="ord-42", amount=10.0, currency="XYZ", reason="Bad currency."
        )


def test_clarify_proposal_carries_the_question_in_reason() -> None:
    proposal = ClaimProposal(
        intent="clarify",
        reason="Which order is this about? I don't see an order number in your message.",
    )

    assert proposal.intent == "clarify"
    assert proposal.order_id is None
    assert proposal.amount is None
    assert proposal.currency is None


def test_clarify_proposal_rejects_refund_fields() -> None:
    """A non-refund intent carrying refund fields is a contradictory
    proposal -- the agent should use intent=refund instead of half-filling
    one, never trusted as a partial refund."""
    with pytest.raises(ValidationError):
        ClaimProposal(
            intent="clarify", order_id="ord-42", reason="Which order is this about?"
        )


def test_out_of_scope_proposal_accepts_reason_only() -> None:
    proposal = ClaimProposal(
        intent="out_of_scope", reason="The user is asking about a password reset."
    )

    assert proposal.intent == "out_of_scope"
    assert proposal.order_id is None


def test_out_of_scope_proposal_rejects_refund_fields() -> None:
    with pytest.raises(ValidationError):
        ClaimProposal(
            intent="out_of_scope", amount=10.0, reason="Not a refund."
        )


def test_proposal_rejects_unknown_intent() -> None:
    with pytest.raises(ValidationError):
        ClaimProposal(intent="delete_all_refunds", reason="Malicious.")


def test_proposal_rejects_empty_reason() -> None:
    with pytest.raises(ValidationError):
        ClaimProposal(intent="out_of_scope", reason="")


def test_proposal_rejects_unknown_fields() -> None:
    """extra="forbid": a field the LLM invents beyond this contract must be
    rejected outright, per CLAUDE.md Section 5a-i, item 3."""
    with pytest.raises(ValidationError):
        ClaimProposal(
            intent="out_of_scope", reason="Not a refund.", admin_override=True
        )
