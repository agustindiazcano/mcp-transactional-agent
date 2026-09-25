"""Executes an approved refund through the MCP server's `execute_refund` tool.

This is the only code path that pushes the refund "button", and it is
deterministic code, never an LLM: the judges approve, then the worker calls
this. The call itself (fresh SSE session per attempt, bounded read timeout,
exponential backoff) is `src/worker/mcp_client.py`'s. `request_id` is the
tool's idempotency key, so a retry after a lost response cannot refund twice.
"""
from typing import Any

from src.worker.mcp_client import McpCallError, McpCallPolicy, call_tool_with_retry

REFUND_TOOL = "execute_refund"

__all__ = ["McpCallPolicy", "RefundExecutionError", "execute_refund_via_mcp"]


class RefundExecutionError(Exception):
    """The refund could not be executed after every retry."""


async def execute_refund_via_mcp(
    *,
    request_id: str,
    transaction_id: str,
    amount: float,
    currency: str,
    policy: McpCallPolicy,
) -> dict[str, Any]:
    """Execute a refund via MCP, retrying with exponential backoff.

    Returns the tool's result (`status` is "executed", or "already_executed"
    for a replay of the same `request_id`). Raises RefundExecutionError once
    `policy.max_retries` attempts have all failed.
    """
    arguments: dict[str, Any] = {
        "request_id": request_id,
        "transaction_id": transaction_id,
        "amount": amount,
        "currency": currency,
    }
    try:
        return await call_tool_with_retry(REFUND_TOOL, arguments, policy)
    except McpCallError as e:
        raise RefundExecutionError(str(e)) from e
