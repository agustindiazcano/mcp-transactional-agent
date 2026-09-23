"""Executes an approved refund through the MCP server's `execute_refund` tool.

This is the only code path that pushes the refund "button", and it is
deterministic code, never an LLM: the judges approve, then the worker calls
this. Every attempt goes through the Phase 1.B security boundary (bearer
token, allowlist, rate limit, argument validation, audit row).

Each attempt opens a fresh SSE session with a bounded `read_timeout_seconds`.
MCP SDK 2.2.0 delivers `tools/call` responses over the SSE stream, so when
the middleware rejects the POST with a 4xx the client never receives a
response and `call_tool` waits forever. The read timeout turns that hang
into an exception, and a new session per attempt means a retry never reuses
a wedged one. Retries back off exponentially; `request_id` is the tool's
idempotency key, so a retry after a lost response cannot refund twice.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, types
from mcp.client.sse import sse_client

from src.core.config import settings

logger = logging.getLogger(__name__)

REFUND_TOOL = "execute_refund"


class RefundExecutionError(Exception):
    """The refund could not be executed after every retry."""


class RefundToolError(Exception):
    """A single attempt reached the tool but got no usable result back."""


@dataclass(frozen=True)
class McpCallPolicy:
    """Where and how to call an MCP tool: endpoint, identity, and retry bounds."""

    server_url: str
    token: str
    max_retries: int
    timeout_seconds: float
    backoff_base_seconds: float

    @classmethod
    def from_settings(cls) -> "McpCallPolicy":
        """Build the policy from the worker's environment configuration."""
        return cls(
            server_url=settings.MCP_SERVER_URL,
            token=settings.MCP_CLIENT_TOKEN,
            max_retries=settings.MCP_TOOL_MAX_RETRIES,
            timeout_seconds=settings.MCP_TOOL_TIMEOUT_SECONDS,
            backoff_base_seconds=settings.MCP_TOOL_BACKOFF_BASE_SECONDS,
        )


async def _call_refund_tool(arguments: dict[str, Any], policy: McpCallPolicy) -> dict[str, Any]:
    """One attempt: open a session, call the tool, return its structured result."""
    headers = {"Authorization": f"Bearer {policy.token}"}
    async with sse_client(policy.server_url, headers=headers) as streams, ClientSession(
        streams[0], streams[1], read_timeout_seconds=policy.timeout_seconds
    ) as session:
        await session.initialize()
        result = await session.call_tool(REFUND_TOOL, arguments)

    if not isinstance(result, types.CallToolResult):
        raise RefundToolError(f"{REFUND_TOOL} returned {type(result).__name__}, not a tool result")
    if result.is_error:
        detail = " ".join(c.text for c in result.content if isinstance(c, types.TextContent))
        raise RefundToolError(f"{REFUND_TOOL} returned an error: {detail}")
    structured = result.structured_content
    if not isinstance(structured, dict):
        raise RefundToolError(f"{REFUND_TOOL} returned no structured result")
    return structured


def _describe(error: BaseException) -> str:
    """Name the real cause of a failed attempt.

    The SSE client reports a rejected POST (e.g. the boundary's 422) as an
    anyio TaskGroup ExceptionGroup whose own message says nothing useful, so
    report its leaf exceptions instead.
    """
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(_describe(inner) for inner in error.exceptions)
    return f"{type(error).__name__}: {error}"


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
    last_error: Exception | None = None

    for attempt in range(policy.max_retries):
        if attempt > 0:
            await asyncio.sleep(policy.backoff_base_seconds * 2 ** (attempt - 1))
        try:
            return await _call_refund_tool(arguments, policy)
        except Exception as e:  # noqa: BLE001 -- any failure is one failed attempt; retried below
            last_error = e
            logger.warning(
                f"execute_refund attempt {attempt + 1}/{policy.max_retries} failed "
                f"for {request_id}: {_describe(e)}"
            )

    detail = _describe(last_error) if last_error else "no attempts made"
    raise RefundExecutionError(detail) from last_error
