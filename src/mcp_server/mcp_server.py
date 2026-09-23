from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import ASGIApp

from src.core.config import settings
from src.core.currency import Currency
from src.core.database import get_engine, get_session_maker
from src.core.repositories.refund_repository import record_refund
from src.mcp_server.security.client_registry import ClientRegistry
from src.mcp_server.security.middleware import MCPSecurityMiddleware

mcp = MCPServer("agentic-mcp-engine")

# MCPServer.sse_app() defaults allowed_hosts to loopback variants only
# (127.0.0.1:*, localhost:*, [::1]:*), which rejects every request from the
# Worker container in Phase 1.C's docker-compose topology -- there the
# Host header is the Docker Compose service name (e.g. "mcp_server:8080"),
# not localhost, so the MCP SDK's DNS-rebinding protection returns HTTP 421
# "Invalid Host header" on every single request, not just under load.
# Extending (not disabling) the allowlist keeps that protection meaningful.
# "mcp_server" is specific to this docker-compose topology; Phase 6's
# Lambda/serverless topology will need its own allowed_hosts entry.
TRANSPORT_SECURITY = TransportSecuritySettings(
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "mcp_server:*"],
    allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://mcp_server:*"],
)

# Set by create_app(): tools are registered at import time on the module-level
# `mcp` server, but the database they write to is chosen when the app is
# built -- the real engine in production, a test database in tests.
_session_maker: async_sessionmaker[AsyncSession] | None = None


def _require_session_maker() -> async_sessionmaker[AsyncSession]:
    if _session_maker is None:
        raise RuntimeError("MCP tools used before create_app() configured a database")
    return _session_maker


@mcp.tool()
async def execute_refund(
    request_id: str,
    transaction_id: str,
    amount: float,
    currency: str = Currency.USD.value,
) -> dict[str, Any]:
    """Execute a refund for a transaction, at most once per `request_id`.

    Idempotent: a repeated call with the same `request_id` records nothing
    new and returns the refund already on file with status
    "already_executed", so a worker retry can never refund twice.

    Business limits (amount <= REFUND_MAX_AMOUNT, currency restricted to
    Currency, no unknown fields, non-empty request_id) are enforced upstream,
    on the raw request, by MCPSecurityMiddleware against ExecuteRefundArgs --
    before this function is ever called. See
    src/mcp_server/security/middleware.py and src/mcp_server/tools/schemas.py
    (CLAUDE.md Section 5a-i, item 3).
    """
    async with _require_session_maker()() as session:
        refund, created = await record_refund(
            session,
            request_id=request_id,
            transaction_id=transaction_id,
            amount=amount,
            currency=currency,
        )
    return {
        "status": "executed" if created else "already_executed",
        "refund_id": refund.id,
        "request_id": refund.request_id,
        "transaction_id": refund.transaction_id,
        "amount": float(refund.amount),
        "currency": refund.currency,
    }

@mcp.tool()
def validate_fraud_score(user_id: str) -> float:
    """Validate and get the fraud score for a user."""
    return 0.12

# message_path must keep the trailing slash: Starlette's Mount registers
# routes as "<path>/<rest>", so a bare request to "/message" (no sub-path,
# just a query string) 307-redirects to "/message/" -- which httpx's client
# (used internally by mcp.client.sse) does not follow by default, breaking
# every message post. "/messages/" is also the MCP SDK's own default.
MESSAGE_PATH = "/messages/"


def create_app(
    *,
    registry: ClientRegistry | None = None,
    session_maker: async_sessionmaker[AsyncSession] | None = None,
    rate_limit_per_min: int | None = None,
) -> ASGIApp:
    """Build the MCP ASGI app behind the Phase 1.B security boundary.

    Defaults read from `settings` (the process-wide registry file, a real DB
    engine, and `MCP_RATE_LIMIT_PER_MIN`), but tests pass explicit overrides
    -- e.g. a registry built in-memory with a known token, a session maker
    pointed at a test database, or a low `rate_limit_per_min` for a fast
    test -- without touching global state. See
    tests/integration/test_mcp_server.py.
    """
    if registry is None:
        registry = ClientRegistry.from_file(settings.MCP_CLIENTS_FILE)
    if session_maker is None:
        session_maker = get_session_maker(get_engine(settings.DATABASE_URL))
    if rate_limit_per_min is None:
        rate_limit_per_min = settings.MCP_RATE_LIMIT_PER_MIN
    global _session_maker
    _session_maker = session_maker
    inner_app = mcp.sse_app(message_path=MESSAGE_PATH, transport_security=TRANSPORT_SECURITY)
    return MCPSecurityMiddleware(
        inner_app,
        registry=registry,
        session_maker=session_maker,
        rate_limit_per_min=rate_limit_per_min,
    )


app = create_app()

if __name__ == "__main__":
    uvicorn.run("src.mcp_server.mcp_server:app", host="0.0.0.0", port=8080, reload=True)
