"""Deterministic evidence check for a refund claim (Part B).

The judges drift between runs (the benchmark saw both approve a €4,800 claim
over the $5,000 limit, and one approve $3,000 on a $30 order), so the facts a
refund depends on are checked in code, before any LLM sees the claim:

- the order exists and belongs to the claiming user;
- the claim is in the order's currency;
- the refund plus what was already refunded on that order fits in the order;
- in USD, at static rates, it does not exceed the policy's human-review limit.

Any failure routes the claim to PENDING_HUMAN_REVIEW: the check can stop an
approval, never grant one. A pure function of its inputs (the MCP tools'
results, passed in), so every outcome is reproducible from the trail.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")


def _money(value: float | str | Decimal) -> Decimal:
    """Exact decimal for an amount the tools return as a float, to the cent."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RefundClaim:
    """The refund a claim asks for, as ingested by the gateway."""

    request_id: str
    user_id: str
    order_id: str
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class EvidenceCheck:
    """Outcome of the check, plus the facts it was computed from."""

    order_id: str
    failures: tuple[str, ...]
    order: Mapping[str, Any] | None = None
    already_refunded: Decimal | None = None
    amount_usd: Decimal | None = None

    @property
    def passed(self) -> bool:
        """True only when no rule failed."""
        return not self.failures

    def to_trail(self) -> dict[str, Any]:
        """The record stored in `judge_trail["evidence"]` (amounts as strings, exact)."""
        return {
            "status": "passed" if self.passed else "failed",
            "order_id": self.order_id,
            "order_amount": str(_money(self.order["amount"])) if self.order else None,
            "order_currency": self.order["currency"] if self.order else None,
            "already_refunded": _str_or_none(self.already_refunded),
            "amount_usd": _str_or_none(self.amount_usd),
            "failures": list(self.failures),
        }

    def summary_for_judges(self) -> dict[str, Any]:
        """The verified facts the judges get in `<reference_context>`."""
        order = self.order or {}
        currency = order.get("currency", "")
        return {
            "order_verified": self.passed,
            "order_date": order.get("created_at"),
            "order_amount": f"{_money(order['amount'])} {currency}" if order else None,
            "already_refunded_on_order": f"{self.already_refunded} {currency}"
            if self.already_refunded is not None
            else None,
        }


def _str_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _previous_refunds(
    claim: RefundClaim, order_currency: str, history: Mapping[str, Any]
) -> tuple[Decimal | None, list[str]]:
    """Total already refunded on the claim's order, excluding this claim's own refund.

    Returns None with a failure when the total can't be trusted.
    """
    refunds: list[Mapping[str, Any]] = list(history.get("refunds", []))
    count = int(history.get("refund_count", len(refunds)))
    if count > len(refunds):
        return None, [
            (
                f"Refund history is incomplete ({len(refunds)} of {count} listed); "
                "previous refunds can't be totaled."
            )
        ]

    total = Decimal(0).quantize(CENT)
    for refund in refunds:
        # A redelivered claim whose refund already executed must not count
        # against itself: execute_refund answers `already_executed` for it.
        if refund.get("order_id") != claim.order_id or refund.get("request_id") == claim.request_id:
            continue
        if refund.get("currency") != order_currency:
            return None, [
                (
                    f"Order {claim.order_id} has a previous refund in "
                    f"{refund.get('currency')}; totals can't be compared."
                )
            ]
        total += _money(refund["amount"])
    return total, []


def check_refund_evidence(
    claim: RefundClaim,
    order_result: Mapping[str, Any],
    refund_history: Mapping[str, Any],
    *,
    fx_rates_to_usd: Mapping[str, float],
    human_review_threshold_usd: float,
) -> EvidenceCheck:
    """Check a refund claim against its order and the user's refund history.

    `order_result` and `refund_history` are the `get_order` and
    `get_refund_history` MCP tools' results, unchanged.
    """
    if order_result.get("status") != "found":
        return EvidenceCheck(
            order_id=claim.order_id, failures=(f"Order {claim.order_id} does not exist.",)
        )

    order: Mapping[str, Any] = order_result["order"]
    failures: list[str] = []
    amount = _money(claim.amount)

    if order.get("user_id") != claim.user_id:
        failures.append(f"Order {claim.order_id} does not belong to the claiming user.")

    already_refunded: Decimal | None = None
    if claim.currency != order.get("currency"):
        failures.append(
            f"Claim currency {claim.currency} does not match the order's currency "
            f"{order.get('currency')}."
        )
    else:
        already_refunded, history_failures = _previous_refunds(
            claim, str(order["currency"]), refund_history
        )
        failures.extend(history_failures)
        if already_refunded is not None:
            # Never below zero: orders refunded past their amount before this
            # check existed still report nothing left, not a negative balance.
            remaining = max(_money(order["amount"]) - already_refunded, Decimal(0).quantize(CENT))
            if amount > remaining:
                failures.append(
                    f"Refund {amount} {claim.currency} exceeds what remains refundable on "
                    f"order {claim.order_id} ({remaining} {claim.currency})."
                )

    amount_usd: Decimal | None = None
    rate = fx_rates_to_usd.get(claim.currency)
    if rate is None:
        failures.append(f"No exchange rate to USD configured for {claim.currency}.")
    else:
        amount_usd = _money(amount * Decimal(str(rate)))
        threshold = _money(human_review_threshold_usd)
        if amount_usd > threshold:
            failures.append(
                f"Refund of {amount_usd} USD exceeds the {threshold} USD limit for "
                "automatic approval."
            )

    return EvidenceCheck(
        order_id=claim.order_id,
        failures=tuple(failures),
        order=order,
        already_refunded=already_refunded,
        amount_usd=amount_usd,
    )
