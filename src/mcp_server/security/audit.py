"""Immutable audit-trail writer for the MCP security boundary (Phase 1.B).

See `src.core.models.McpAuditLog` and CLAUDE.md Section 4: every invocation,
including denied and rate-limited ones, gets a row; a failed write on the
allow path must deny the call rather than let it proceed.
"""

from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import McpAuditLog

AuditDecision = Literal[
    "ALLOWED",
    "DENIED_UNAUTHENTICATED",
    "DENIED_UNAUTHORIZED",
    "DENIED_VALIDATION",
]

# Argument keys whose values are masked before being written to the audit
# table. Matched case-insensitively against top-level argument names.
_PII_KEYS = {"user_id", "email", "phone", "ssn", "account_number", "name", "address"}
_MASK = "***MASKED***"


def mask_pii(arguments: dict[str, Any]) -> dict[str, Any]:
    """Replace values of PII-looking keys, keeping every key present so the
    audit row still shows which fields were sent.
    """
    return {
        key: (_MASK if key.lower() in _PII_KEYS else value) for key, value in arguments.items()
    }


async def write_audit_log(
    session: AsyncSession,
    *,
    client_id: str,
    tool: str | None,
    arguments: dict[str, Any],
    decision: AuditDecision,
    result: str | None,
) -> None:
    """Insert and commit one audit row.

    Raises on failure. Callers on the allow path must treat that as "deny" --
    the boundary fails closed, not open.
    """
    row = McpAuditLog(
        client_id=client_id,
        tool=tool,
        arguments=mask_pii(arguments),
        decision=decision,
        result=result,
    )
    session.add(row)
    await session.commit()
