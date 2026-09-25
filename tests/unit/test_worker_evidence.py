"""Unit tests for src.worker.evidence.

Fetches a claim's evidence through the MCP read tools (`get_order`,
`get_refund_history`) and runs the deterministic check on it. An MCP outage
is EvidenceUnavailableError (the worker routes the claim to human review);
a claim with no user to verify against fails the check without a call.
"""
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.worker.evidence import EvidenceUnavailableError, verify_claim_evidence
from src.worker.mcp_client import McpCallError, McpCallPolicy

POLICY = McpCallPolicy(
    server_url="http://mcp_server:8080/sse",
    token="worker-token",
    max_retries=1,
    timeout_seconds=1.0,
    backoff_base_seconds=0.0,
)

BODY: dict[str, Any] = {
    "request_id": "req-1",
    "user_id": "user-1",
    "order_id": "ord-1",
    "amount": 45.5,
    "currency": "USD",
}

ORDER = {
    "status": "found",
    "order": {
        "order_id": "ord-1",
        "user_id": "user-1",
        "amount": 100.0,
        "currency": "USD",
        "created_at": "2026-09-12T10:00:00+00:00",
    },
}
HISTORY = {"user_id": "user-1", "refund_count": 0, "totals_by_currency": {}, "refunds": []}


def _tools(order: dict[str, Any] = ORDER, history: dict[str, Any] = HISTORY) -> AsyncMock:
    async def call(tool: str, arguments: dict[str, Any], policy: McpCallPolicy) -> dict[str, Any]:
        return order if tool == "get_order" else history

    return AsyncMock(side_effect=call)


@pytest.mark.asyncio
async def test_fetches_the_order_and_the_users_full_history_then_checks() -> None:
    tools = _tools()

    with patch("src.worker.evidence.call_tool_with_retry", tools):
        result = await verify_claim_evidence(BODY, POLICY)

    assert result.passed
    assert result.already_refunded == Decimal("0.00")
    calls = {c.args[0]: c.args[1] for c in tools.await_args_list}
    assert calls == {
        "get_order": {"order_id": "ord-1"},
        "get_refund_history": {"user_id": "user-1", "limit": 100},
    }


@pytest.mark.asyncio
async def test_currency_defaults_to_usd_like_the_refund_call() -> None:
    with patch("src.worker.evidence.call_tool_with_retry", _tools()):
        result = await verify_claim_evidence({**BODY, "currency": None}, POLICY)

    assert result.passed


@pytest.mark.asyncio
async def test_a_failed_check_is_returned_not_raised() -> None:
    not_found = {"status": "not_found", "order_id": "ord-1"}

    with patch("src.worker.evidence.call_tool_with_retry", _tools(order=not_found)):
        result = await verify_claim_evidence(BODY, POLICY)

    assert not result.passed


@pytest.mark.asyncio
async def test_an_mcp_outage_raises_evidence_unavailable() -> None:
    tools = AsyncMock(side_effect=McpCallError("ConnectionError: refused"))

    with (
        patch("src.worker.evidence.call_tool_with_retry", tools),
        pytest.raises(EvidenceUnavailableError, match="refused"),
    ):
        await verify_claim_evidence(BODY, POLICY)


@pytest.mark.asyncio
async def test_a_claim_without_a_user_fails_without_calling_mcp() -> None:
    """The boundary rejects an empty user_id with a 4xx, which the MCP SDK
    turns into a hang until the read timeout, on every retry."""
    tools = _tools()

    with patch("src.worker.evidence.call_tool_with_retry", tools):
        result = await verify_claim_evidence({**BODY, "user_id": ""}, POLICY)

    assert not result.passed
    assert result.failures == ("Claim has no user_id to verify the order against.",)
    tools.assert_not_awaited()
