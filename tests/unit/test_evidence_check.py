"""Unit tests for src.core.services.evidence_check.

The deterministic check (Part B) a refund claim must pass before the judges
see it: the order exists, belongs to the claim's user, is in the claim's
currency, and the refund plus what was already refunded on that order does
not exceed the order; above the policy's $5,000 (in USD, at static rates) it
goes to human review. Any failure routes the claim to PENDING_HUMAN_REVIEW
without an LLM call, so a judge can never approve it.
"""
from decimal import Decimal
from typing import Any

from src.core.services.evidence_check import RefundClaim, check_refund_evidence

RATES = {"USD": 1.0, "EUR": 1.1367, "GBP": 1.322}
THRESHOLD_USD = 5000.0

CLAIM = RefundClaim(
    request_id="req-1", user_id="user-1", order_id="ord-1", amount=Decimal("45.50"), currency="USD"
)


def _order(**overrides: Any) -> dict[str, Any]:
    order = {
        "order_id": "ord-1",
        "user_id": "user-1",
        "amount": 100.0,
        "currency": "USD",
        "created_at": "2026-09-12T10:00:00+00:00",
    }
    return {"status": "found", "order": {**order, **overrides}}


def _refund(amount: float, *, order_id: str = "ord-1", request_id: str = "old-1",
            currency: str = "USD") -> dict[str, Any]:
    return {
        "request_id": request_id,
        "order_id": order_id,
        "amount": amount,
        "currency": currency,
        "created_at": "2026-09-20T10:00:00+00:00",
    }


def _history(*refunds: dict[str, Any], refund_count: int | None = None) -> dict[str, Any]:
    return {
        "user_id": "user-1",
        "refund_count": len(refunds) if refund_count is None else refund_count,
        "totals_by_currency": {},
        "refunds": list(refunds),
    }


def _check(claim: RefundClaim = CLAIM, order: dict[str, Any] | None = None,
           history: dict[str, Any] | None = None) -> Any:
    return check_refund_evidence(
        claim,
        order if order is not None else _order(),
        history if history is not None else _history(),
        fx_rates_to_usd=RATES,
        human_review_threshold_usd=THRESHOLD_USD,
    )


def test_a_refund_within_its_order_passes() -> None:
    result = _check()

    assert result.passed
    assert result.failures == ()
    assert result.amount_usd == Decimal("45.50")
    assert result.already_refunded == Decimal(0)


def test_an_order_that_does_not_exist_fails() -> None:
    result = _check(order={"status": "not_found", "order_id": "ord-1"})

    assert not result.passed
    assert result.failures == ("Order ord-1 does not exist.",)


def test_an_order_owned_by_another_user_fails() -> None:
    result = _check(order=_order(user_id="user-2"))

    assert not result.passed
    assert "Order ord-1 does not belong to the claiming user." in result.failures


def test_a_currency_different_from_the_order_fails() -> None:
    claim = RefundClaim(request_id="req-1", user_id="user-1", order_id="ord-1",
                        amount=Decimal("45.50"), currency="EUR")

    result = _check(claim)

    assert not result.passed
    assert "Claim currency EUR does not match the order's currency USD." in result.failures


def test_a_refund_larger_than_the_order_fails() -> None:
    """The benchmark's `b2-reject-04`: a $3,000 refund on a $30 charger."""
    claim = RefundClaim(request_id="req-1", user_id="user-1", order_id="ord-1",
                        amount=Decimal(3000), currency="USD")

    result = _check(claim, order=_order(amount=30.0))

    assert not result.passed
    assert "Refund 3000.00 USD exceeds what remains refundable on order ord-1 (30.00 USD)." in (
        result.failures
    )


def test_a_refund_of_exactly_what_remains_passes() -> None:
    history = _history(_refund(54.50))

    result = _check(history=history)

    assert result.passed
    assert result.already_refunded == Decimal("54.50")


def test_previous_refunds_on_the_same_order_count_against_it() -> None:
    history = _history(_refund(60.0), _refund(999.0, order_id="ord-other"))

    result = _check(history=history)

    assert not result.passed
    assert result.already_refunded == Decimal("60.00")
    assert "Refund 45.50 USD exceeds what remains refundable on order ord-1 (40.00 USD)." in (
        result.failures
    )


def test_this_claims_own_refund_is_not_counted_against_it() -> None:
    """A redelivered claim whose refund already executed (the sweeper's requeue
    after a crash between execute_refund and the final commit) must pass again,
    so execute_refund answers `already_executed` instead of the claim going to
    human review."""
    history = _history(_refund(45.50, request_id="req-1"), _refund(54.50))

    result = _check(history=history)

    assert result.passed
    assert result.already_refunded == Decimal("54.50")


def test_a_previous_refund_in_another_currency_fails_closed() -> None:
    history = _history(_refund(10.0, currency="EUR"))

    result = _check(history=history)

    assert not result.passed
    assert "Order ord-1 has a previous refund in EUR; totals can't be compared." in (
        result.failures
    )


def test_a_truncated_refund_history_fails_closed() -> None:
    """If the listed refunds are fewer than the count, an older refund on this
    order could be missing from the total."""
    history = _history(_refund(1.0), refund_count=150)

    result = _check(history=history)

    assert not result.passed
    assert "Refund history is incomplete (1 of 150 listed); previous refunds can't be totaled." in (
        result.failures
    )


def test_a_refund_over_the_usd_threshold_goes_to_human_review() -> None:
    """The €4,800 case: under $5,000 in its own currency's digits, over it in USD."""
    claim = RefundClaim(request_id="req-1", user_id="user-1", order_id="ord-1",
                        amount=Decimal(4800), currency="EUR")

    result = _check(claim, order=_order(amount=6000.0, currency="EUR"))

    assert not result.passed
    assert result.amount_usd == Decimal("5456.16")
    assert "Refund of 5456.16 USD exceeds the 5000.00 USD limit for automatic approval." in (
        result.failures
    )


def test_a_refund_of_exactly_the_threshold_passes() -> None:
    claim = RefundClaim(request_id="req-1", user_id="user-1", order_id="ord-1",
                        amount=Decimal(5000), currency="USD")

    result = _check(claim, order=_order(amount=5000.0))

    assert result.passed


def test_a_currency_without_an_exchange_rate_fails_closed() -> None:
    claim = RefundClaim(request_id="req-1", user_id="user-1", order_id="ord-1",
                        amount=Decimal(10), currency="JPY")

    result = _check(claim, order=_order(currency="JPY"))

    assert not result.passed
    assert "No exchange rate to USD configured for JPY." in result.failures


def test_the_trail_records_inputs_and_outcome() -> None:
    result = _check(history=_history(_refund(20.0)))

    assert result.to_trail() == {
        "status": "passed",
        "order_id": "ord-1",
        "order_amount": "100.00",
        "order_currency": "USD",
        "already_refunded": "20.00",
        "amount_usd": "45.50",
        "failures": [],
    }


def test_the_judges_summary_states_the_verified_facts() -> None:
    summary = _check(history=_history(_refund(20.0))).summary_for_judges()

    assert summary == {
        "order_verified": True,
        "order_date": "2026-09-12T10:00:00+00:00",
        "order_amount": "100.00 USD",
        "already_refunded_on_order": "20.00 USD",
    }


def test_an_already_over_refunded_order_reports_nothing_remaining() -> None:
    """Found in the dev DB: $182 refunded on a $45.50 order, from before this check."""
    history = _history(_refund(182.0))

    result = _check(order=_order(amount=45.5), history=history)

    assert "Refund 45.50 USD exceeds what remains refundable on order ord-1 (0.00 USD)." in (
        result.failures
    )
