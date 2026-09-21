"""Sliding-window rate limiting for the MCP security boundary (Phase 1.B).

Limits are computed from `mcp_audit_logs` (not a separate counter table or
Redis), so the limit holds across multiple MCP replicas without adding
another piece of infrastructure -- see CLAUDE.md Section 5a-i, item 4, and
README's "Why rate limiting and audit in PostgreSQL, not Redis or log
files?" ADR. That ADR's trade-off applies here too: this is a
count-then-decide check with no row lock, so concurrent calls near the limit
can overshoot it slightly -- acceptable at this system's call volume.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import McpAuditLog

WINDOW = timedelta(minutes=1)


async def is_rate_limited(
    session: AsyncSession,
    *,
    client_id: str,
    tool: str,
    limit_per_min: int,
    now: datetime | None = None,
) -> bool:
    """True if `client_id` has already made `limit_per_min` or more calls to
    `tool` in the trailing 1-minute window.

    Counts every audit row for (client_id, tool) regardless of `decision` --
    including past denials -- so a client retrying malformed arguments or a
    disallowed tool still consumes its quota instead of bypassing the limit
    for free. `now` defaults to the current time; tests pass it explicitly to
    assert exact window-boundary behavior without a real 60-second wait.
    """
    window_start = (now or datetime.now(UTC)) - WINDOW
    stmt = select(func.count(McpAuditLog.id)).where(
        McpAuditLog.client_id == client_id,
        McpAuditLog.tool == tool,
        McpAuditLog.created_at >= window_start,
    )
    result = await session.execute(stmt)
    count = result.scalar_one()
    return count >= limit_per_min
