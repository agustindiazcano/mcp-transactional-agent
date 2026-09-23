"""Unit tests for the gateway's ingestion schema (src/api/schemas.py).

`order_id`, `amount`, and `currency` are optional -- a free-text claim is
still accepted and judged -- but when present they are validated at the
gateway with the same business limits the MCP boundary enforces, so an
out-of-bounds refund is rejected with a 422 at ingestion instead of being
approved by the judges and then failing at execution time.
"""
import pytest
from pydantic import ValidationError

from src.api.schemas import ClaimRequest
from src.core.config import settings
from src.core.currency import Currency


def test_claim_without_refund_details_is_still_valid() -> None:
    claim = ClaimRequest(user_id="usr-1", claim_text="My order arrived broken.")

    assert claim.order_id is None
    assert claim.amount is None
    assert claim.currency is None


def test_claim_accepts_refund_details() -> None:
    claim = ClaimRequest(
        user_id="usr-1",
        claim_text="Refund my order please.",
        order_id="ord-42",
        amount=49.99,
        currency="EUR",
    )

    assert claim.order_id == "ord-42"
    assert claim.amount == 49.99
    assert claim.currency is Currency.EUR


def test_claim_rejects_amount_above_refund_max() -> None:
    with pytest.raises(ValidationError):
        ClaimRequest(
            user_id="usr-1",
            claim_text="Refund",
            order_id="ord-42",
            amount=settings.REFUND_MAX_AMOUNT + 1,
        )


def test_claim_rejects_non_positive_amount() -> None:
    with pytest.raises(ValidationError):
        ClaimRequest(user_id="usr-1", claim_text="Refund", order_id="ord-42", amount=0)


def test_claim_rejects_unknown_currency() -> None:
    with pytest.raises(ValidationError):
        ClaimRequest(user_id="usr-1", claim_text="Refund", amount=10.0, currency="XYZ")


def test_claim_rejects_empty_order_id() -> None:
    with pytest.raises(ValidationError):
        ClaimRequest(user_id="usr-1", claim_text="Refund", order_id="", amount=10.0)


def test_currency_serializes_as_plain_string_for_the_queue() -> None:
    claim = ClaimRequest(user_id="usr-1", claim_text="Refund", amount=10.0, currency="GBP")

    assert '"currency":"GBP"' in claim.model_dump_json()
