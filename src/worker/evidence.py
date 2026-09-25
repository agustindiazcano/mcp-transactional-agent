"""Fetches a claim's evidence through MCP and checks it, before the judges.

The worker calls the read-only `get_order` and `get_refund_history` tools
(through the Phase 1.B boundary, like every tool call) and hands their
results to `src/core/services/evidence_check.py`'s pure check. A failed
check is returned; an MCP outage raises EvidenceUnavailableError. Either way
the worker routes the claim to PENDING_HUMAN_REVIEW, without an LLM call.
"""
from decimal import Decimal
from typing import Any

from src.core.config import settings
from src.core.currency import Currency
from src.core.services.evidence_check import (
    EvidenceCheck,
    RefundClaim,
    check_refund_evidence,
)
from src.worker.mcp_client import McpCallError, McpCallPolicy, call_tool_with_retry

# The boundary's maximum (GetRefundHistoryArgs). A user with more refunds
# than this fails the check closed, since the order's total may be incomplete.
REFUND_HISTORY_LIMIT = 100


class EvidenceUnavailableError(Exception):
    """The evidence could not be fetched after every retry."""


async def verify_claim_evidence(body: dict[str, Any], policy: McpCallPolicy) -> EvidenceCheck:
    """Fetch the order and refund history for a claim with refund details, and check them.

    `body` must carry `order_id` and `amount`; the currency defaults to USD,
    as it does for the refund call.
    """
    order_id = str(body["order_id"])
    user_id = str(body.get("user_id") or "")
    if not user_id:
        return EvidenceCheck(
            order_id=order_id,
            failures=("Claim has no user_id to verify the order against.",),
        )

    claim = RefundClaim(
        request_id=str(body["request_id"]),
        user_id=user_id,
        order_id=order_id,
        amount=Decimal(str(body["amount"])),
        currency=str(body.get("currency") or Currency.USD.value),
    )
    try:
        order = await call_tool_with_retry("get_order", {"order_id": order_id}, policy)
        history = await call_tool_with_retry(
            "get_refund_history", {"user_id": user_id, "limit": REFUND_HISTORY_LIMIT}, policy
        )
    except McpCallError as e:
        raise EvidenceUnavailableError(str(e)) from e

    return check_refund_evidence(
        claim,
        order,
        history,
        fx_rates_to_usd=settings.FX_RATES_TO_USD,
        human_review_threshold_usd=settings.REFUND_HUMAN_REVIEW_THRESHOLD_USD,
    )
