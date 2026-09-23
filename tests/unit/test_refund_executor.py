"""Unit tests for src.worker.refund_executor.

The executor is the only code path that pushes the refund "button": it calls
the MCP `execute_refund` tool after the judges approve. Each attempt opens a
fresh SSE session because MCP SDK 2.2.0 hangs in `call_tool` when the Phase
1.B middleware rejects a POST with a 4xx -- a bounded `read_timeout_seconds`
turns that hang into an exception, and a new session per attempt means a
retry never reuses a wedged one.
"""
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import types

from src.core.config import settings
from src.worker.refund_executor import (
    McpCallPolicy,
    RefundExecutionError,
    execute_refund_via_mcp,
)

POLICY = McpCallPolicy(
    server_url="http://mcp_server:8080/sse",
    token="worker-token",
    max_retries=3,
    timeout_seconds=7.5,
    backoff_base_seconds=0.5,
)

REFUND_KWARGS: dict[str, Any] = {
    "request_id": "req-1",
    "transaction_id": "ord-1",
    "amount": 50.0,
    "currency": "USD",
}

EXECUTED = {
    "status": "executed",
    "refund_id": 1,
    "request_id": "req-1",
    "transaction_id": "ord-1",
    "amount": 50.0,
    "currency": "USD",
}


def _tool_result(
    *, is_error: bool = False, structured: dict[str, Any] | None = None
) -> types.CallToolResult:
    content = [types.TextContent(type="text", text="boom")] if is_error else []
    return types.CallToolResult(content=content, structured_content=structured, is_error=is_error)


def _wire_mcp(
    mock_sse: MagicMock, mock_cs: MagicMock, call_tool: AsyncMock
) -> AsyncMock:
    session = AsyncMock()
    session.initialize = AsyncMock()
    session.call_tool = call_tool
    mock_sse.return_value.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
    mock_sse.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_cs.return_value.__aenter__ = AsyncMock(return_value=session)
    mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_success_on_first_attempt_returns_tool_result() -> None:
    call_tool = AsyncMock(return_value=_tool_result(structured=EXECUTED))

    with (
        patch("src.worker.refund_executor.sse_client") as mock_sse,
        patch("src.worker.refund_executor.ClientSession") as mock_cs,
        patch("src.worker.refund_executor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        _wire_mcp(mock_sse, mock_cs, call_tool)
        result = await execute_refund_via_mcp(**REFUND_KWARGS, policy=POLICY)

    assert result == EXECUTED
    call_tool.assert_awaited_once_with("execute_refund", REFUND_KWARGS)
    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_is_authenticated_and_bounded_by_read_timeout() -> None:
    call_tool = AsyncMock(return_value=_tool_result(structured=EXECUTED))

    with (
        patch("src.worker.refund_executor.sse_client") as mock_sse,
        patch("src.worker.refund_executor.ClientSession") as mock_cs,
    ):
        _wire_mcp(mock_sse, mock_cs, call_tool)
        await execute_refund_via_mcp(**REFUND_KWARGS, policy=POLICY)

    sse_args, sse_kwargs = mock_sse.call_args
    assert POLICY.server_url in (*sse_args, sse_kwargs.get("url"))
    assert sse_kwargs["headers"] == {"Authorization": "Bearer worker-token"}
    assert mock_cs.call_args.kwargs["read_timeout_seconds"] == 7.5


@pytest.mark.asyncio
async def test_transient_failure_retries_with_new_session_and_backoff() -> None:
    call_tool = AsyncMock(
        side_effect=[TimeoutError("hung on 4xx"), _tool_result(structured=EXECUTED)]
    )

    with (
        patch("src.worker.refund_executor.sse_client") as mock_sse,
        patch("src.worker.refund_executor.ClientSession") as mock_cs,
        patch("src.worker.refund_executor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        _wire_mcp(mock_sse, mock_cs, call_tool)
        result = await execute_refund_via_mcp(**REFUND_KWARGS, policy=POLICY)

    assert result == EXECUTED
    assert call_tool.await_count == 2
    assert mock_sse.call_count == 2  # a fresh session per attempt
    mock_sleep.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
async def test_backoff_is_exponential_between_attempts() -> None:
    call_tool = AsyncMock(side_effect=RuntimeError("mcp down"))

    with (
        patch("src.worker.refund_executor.sse_client") as mock_sse,
        patch("src.worker.refund_executor.ClientSession") as mock_cs,
        patch("src.worker.refund_executor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        _wire_mcp(mock_sse, mock_cs, call_tool)
        with pytest.raises(RefundExecutionError):
            await execute_refund_via_mcp(**REFUND_KWARGS, policy=POLICY)

    assert call_tool.await_count == 3
    assert [c.args[0] for c in mock_sleep.await_args_list] == [0.5, 1.0]


@pytest.mark.asyncio
async def test_tool_error_result_counts_as_failed_attempt() -> None:
    call_tool = AsyncMock(return_value=_tool_result(is_error=True))

    with (
        patch("src.worker.refund_executor.sse_client") as mock_sse,
        patch("src.worker.refund_executor.ClientSession") as mock_cs,
        patch("src.worker.refund_executor.asyncio.sleep", new_callable=AsyncMock),
    ):
        _wire_mcp(mock_sse, mock_cs, call_tool)
        with pytest.raises(RefundExecutionError, match="boom"):
            await execute_refund_via_mcp(**REFUND_KWARGS, policy=POLICY)

    assert call_tool.await_count == 3


@pytest.mark.asyncio
async def test_result_without_structured_content_counts_as_failed_attempt() -> None:
    call_tool = AsyncMock(return_value=_tool_result(structured=None))

    with (
        patch("src.worker.refund_executor.sse_client") as mock_sse,
        patch("src.worker.refund_executor.ClientSession") as mock_cs,
        patch("src.worker.refund_executor.asyncio.sleep", new_callable=AsyncMock),
    ):
        _wire_mcp(mock_sse, mock_cs, call_tool)
        with pytest.raises(RefundExecutionError, match="no structured result"):
            await execute_refund_via_mcp(**REFUND_KWARGS, policy=POLICY)


@pytest.mark.asyncio
async def test_policy_from_settings_reads_worker_configuration() -> None:
    policy = McpCallPolicy.from_settings()

    assert policy.server_url == settings.MCP_SERVER_URL
    assert policy.token == settings.MCP_CLIENT_TOKEN
    assert policy.max_retries == settings.MCP_TOOL_MAX_RETRIES
    assert policy.timeout_seconds == settings.MCP_TOOL_TIMEOUT_SECONDS
    assert policy.backoff_base_seconds == settings.MCP_TOOL_BACKOFF_BASE_SECONDS


@pytest.mark.asyncio
async def test_connection_failure_counts_as_failed_attempt() -> None:
    with (
        patch("src.worker.refund_executor.sse_client") as mock_sse,
        patch("src.worker.refund_executor.ClientSession"),
        patch("src.worker.refund_executor.asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_sse.return_value.__aenter__ = AsyncMock(side_effect=ConnectionError("refused"))
        mock_sse.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(RefundExecutionError, match="refused"):
            await execute_refund_via_mcp(**REFUND_KWARGS, policy=POLICY)

    assert mock_sse.call_count == 3


@pytest.mark.asyncio
async def test_task_group_failure_reports_the_underlying_cause() -> None:
    """The SSE client surfaces a rejected POST as an anyio TaskGroup
    ExceptionGroup; the recorded error must name the real cause (e.g. the
    boundary's 422), not the generic group message -- it ends up in the
    transaction's trail and the dashboard."""
    group = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [RuntimeError("Client error '422 Unprocessable Entity'")],
    )
    call_tool = AsyncMock(side_effect=group)

    with (
        patch("src.worker.refund_executor.sse_client") as mock_sse,
        patch("src.worker.refund_executor.ClientSession") as mock_cs,
        patch("src.worker.refund_executor.asyncio.sleep", new_callable=AsyncMock),
    ):
        _wire_mcp(mock_sse, mock_cs, call_tool)
        with pytest.raises(RefundExecutionError, match="RuntimeError: Client error '422"):
            await execute_refund_via_mcp(**REFUND_KWARGS, policy=POLICY)
