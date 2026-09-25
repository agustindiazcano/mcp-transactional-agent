"""Unit tests for src.worker.mcp_client.

The worker's one way to call an MCP tool: a fresh SSE session per attempt,
bounded by `read_timeout_seconds` (MCP SDK 2.2.0 hangs in `call_tool` when
the Phase 1.B boundary rejects a POST with a 4xx), exponential backoff
between attempts. Used by the refund executor and the evidence fetch.
"""
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import types

from src.worker.mcp_client import McpCallError, McpCallPolicy, call_tool_with_retry

POLICY = McpCallPolicy(
    server_url="http://mcp_server:8080/sse",
    token="worker-token",
    max_retries=2,
    timeout_seconds=5.0,
    backoff_base_seconds=0.25,
)

FOUND = {"status": "found", "order": {"order_id": "ord-1"}}


def _wire(mock_sse: MagicMock, mock_cs: MagicMock, call_tool: AsyncMock) -> None:
    session = AsyncMock()
    session.initialize = AsyncMock()
    session.call_tool = call_tool
    mock_sse.return_value.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
    mock_sse.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_cs.return_value.__aenter__ = AsyncMock(return_value=session)
    mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)


def _result(structured: dict[str, Any] | None) -> types.CallToolResult:
    return types.CallToolResult(content=[], structured_content=structured, is_error=False)


@pytest.mark.asyncio
async def test_calls_the_named_tool_with_its_arguments() -> None:
    call_tool = AsyncMock(return_value=_result(FOUND))

    with (
        patch("src.worker.mcp_client.sse_client") as mock_sse,
        patch("src.worker.mcp_client.ClientSession") as mock_cs,
    ):
        _wire(mock_sse, mock_cs, call_tool)
        result = await call_tool_with_retry("get_order", {"order_id": "ord-1"}, POLICY)

    assert result == FOUND
    call_tool.assert_awaited_once_with("get_order", {"order_id": "ord-1"})


@pytest.mark.asyncio
async def test_exhausted_retries_raise_mcp_call_error_naming_the_tool() -> None:
    call_tool = AsyncMock(side_effect=TimeoutError("hung on 4xx"))

    with (
        patch("src.worker.mcp_client.sse_client") as mock_sse,
        patch("src.worker.mcp_client.ClientSession") as mock_cs,
        patch("src.worker.mcp_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        _wire(mock_sse, mock_cs, call_tool)
        with pytest.raises(McpCallError, match="TimeoutError: hung on 4xx"):
            await call_tool_with_retry("get_refund_history", {"user_id": "u"}, POLICY)

    assert call_tool.await_count == 2
    mock_sleep.assert_awaited_once_with(0.25)
