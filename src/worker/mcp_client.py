"""The worker's one way to call an MCP tool, with retries.

Every call goes through the Phase 1.B security boundary (bearer token,
allowlist, rate limit, argument validation, audit row). Each attempt opens a
fresh SSE session with a bounded `read_timeout_seconds`: MCP SDK 2.2.0
delivers `tools/call` responses over the SSE stream, so when the middleware
rejects the POST with a 4xx the client never receives a response and
`call_tool` waits forever. The read timeout turns that hang into an
exception, and a new session per attempt means a retry never reuses a wedged
one. Retries back off exponentially.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession, types
from mcp.client.sse import sse_client

from src.core.config import settings

logger = logging.getLogger(__name__)


class McpCallError(Exception):
    """The tool call failed on every attempt."""


class McpToolError(Exception):
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


async def _call_tool_once(
    tool: str, arguments: dict[str, Any], policy: McpCallPolicy
) -> dict[str, Any]:
    """One attempt: open a session, call the tool, return its structured result."""
    headers = {"Authorization": f"Bearer {policy.token}"}
    async with sse_client(policy.server_url, headers=headers) as streams, ClientSession(
        streams[0], streams[1], read_timeout_seconds=policy.timeout_seconds
    ) as session:
        await session.initialize()
        result = await session.call_tool(tool, arguments)

    if not isinstance(result, types.CallToolResult):
        raise McpToolError(f"{tool} returned {type(result).__name__}, not a tool result")
    if result.is_error:
        detail = " ".join(c.text for c in result.content if isinstance(c, types.TextContent))
        raise McpToolError(f"{tool} returned an error: {detail}")
    structured = result.structured_content
    if not isinstance(structured, dict):
        raise McpToolError(f"{tool} returned no structured result")
    return structured


def describe_error(error: BaseException) -> str:
    """Name the real cause of a failed attempt.

    The SSE client reports a rejected POST (e.g. the boundary's 422) as an
    anyio TaskGroup ExceptionGroup whose own message says nothing useful, so
    report its leaf exceptions instead.
    """
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(describe_error(inner) for inner in error.exceptions)
    return f"{type(error).__name__}: {error}"


_RETRYABLE_CLIENT_ERRORS = frozenset({408, 429})


def is_permanent_rejection(error: BaseException) -> bool:
    """True when the MCP boundary rejected the call with a 4xx a retry can't fix.

    A 401/403/404/422 depends only on the request or the caller's identity, so
    repeating it just spends rate-limit quota. 408 and 429 are transient. The
    SSE client wraps the HTTP error in an ExceptionGroup, so look at its leaves.
    """
    if isinstance(error, BaseExceptionGroup):
        return any(is_permanent_rejection(inner) for inner in error.exceptions)
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return 400 <= status < 500 and status not in _RETRYABLE_CLIENT_ERRORS
    return False


async def call_tool_with_retry(
    tool: str, arguments: dict[str, Any], policy: McpCallPolicy
) -> dict[str, Any]:
    """Call `tool` via MCP, retrying with exponential backoff.

    Returns the tool's structured result. Raises McpCallError once
    `policy.max_retries` attempts have all failed, or at once on a 4xx
    rejection from the boundary that a retry can't fix.
    """
    last_error: Exception | None = None

    for attempt in range(policy.max_retries):
        if attempt > 0:
            await asyncio.sleep(policy.backoff_base_seconds * 2 ** (attempt - 1))
        try:
            return await _call_tool_once(tool, arguments, policy)
        except Exception as e:  # noqa: BLE001 -- any failure is one failed attempt; retried below
            last_error = e
            logger.warning(
                f"{tool} attempt {attempt + 1}/{policy.max_retries} failed: {describe_error(e)}"
            )
            if is_permanent_rejection(e):
                break

    detail = describe_error(last_error) if last_error else "no attempts made"
    raise McpCallError(detail) from last_error
