import asyncio
import hashlib
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select, text

from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.models import Base, McpAuditLog
from src.mcp_server.security.client_registry import ClientRegistry

# We need to make sure the app can be imported
# The app will be in src.mcp_server.mcp_server.app
try:
    from src.mcp_server.mcp_server import create_app
except ImportError:
    # If the file doesn't exist yet, we create a dummy app for the test collection to pass
    # so we can see it fail during execution
    from fastapi import FastAPI

    def create_app(**_kwargs):  # type: ignore[misc]
        return FastAPI()


VALID_TOKEN = "test-worker-token"
VALID_TOKEN_HASH = hashlib.sha256(VALID_TOKEN.encode("utf-8")).hexdigest()


def _test_registry() -> ClientRegistry:
    return ClientRegistry.from_records(
        [
            {
                "client_id": "test-worker",
                "token_hash": VALID_TOKEN_HASH,
                "allowed_tools": ["execute_refund", "validate_fraud_score"],
            }
        ]
    )


@pytest_asyncio.fixture
async def db_engine():
    engine = get_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    # Never Base.metadata.drop_all(): see test_worker.py/test_database.py for
    # why -- only clear this file's own rows.
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE mcp_audit_logs RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def app_under_test(db_engine):
    session_maker = get_session_maker(db_engine)
    return create_app(registry=_test_registry(), session_maker=session_maker)


@pytest_asyncio.fixture
async def async_mcp_client(app_under_test):
    transport = ASGITransport(app=app_under_test)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        yield client


@pytest.mark.asyncio
async def test_mcp_sse_endpoint_exists(async_mcp_client):
    """An authenticated caller can establish the SSE transport endpoint."""
    try:
        async with asyncio.timeout(0.5):
            async with async_mcp_client.stream(
                "GET", "/sse", headers={"Authorization": f"Bearer {VALID_TOKEN}"}
            ) as response:
                assert response.status_code == 200
    except TimeoutError:
        pass  # Expected to timeout because it's a long-lived SSE connection


@pytest.mark.asyncio
async def test_mcp_tools_registered():
    """Verify that the required tools are registered on the MCP server."""
    from src.mcp_server.mcp_server import mcp

    tools = mcp._tool_manager._tools if hasattr(mcp, '_tool_manager') else {}
    tool_names = list(tools.keys()) if isinstance(tools, dict) else [t.name for t in tools]

    assert "execute_refund" in tool_names
    assert "validate_fraud_score" in tool_names


@pytest.mark.asyncio
async def test_sse_endpoint_rejects_missing_token(async_mcp_client):
    """No Authorization header at all -> 401, before any MCP session starts."""
    response = await async_mcp_client.get("/sse")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sse_endpoint_rejects_invalid_token(async_mcp_client):
    """A token that hashes to nothing in the registry -> 401."""
    response = await async_mcp_client.get(
        "/sse", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tool_call_over_refund_limit_is_blocked_and_audited(async_mcp_client, db_engine):
    """A refund above REFUND_MAX_AMOUNT is rejected before execution, and the
    attempt is recorded in the immutable audit trail."""
    over_limit_amount = settings.REFUND_MAX_AMOUNT + 1
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "execute_refund",
            "arguments": {
                "transaction_id": "txn-over-limit",
                "amount": over_limit_amount,
                "currency": "USD",
            },
        },
    }

    # Establish a session first: the security boundary applies uniformly to
    # every request, but there's no live SSE session to carry a response over
    # in this test, so we only assert on the HTTP-level rejection and the
    # audit row -- both happen before the message reaches the MCP session.
    response = await async_mcp_client.post(
        "/messages/?session_id=00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
        content=json.dumps(payload),
    )

    assert response.status_code == 422

    session_maker = get_session_maker(db_engine)
    async with session_maker() as session:
        result = await session.execute(
            select(McpAuditLog).where(McpAuditLog.tool == "execute_refund")
        )
        rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].decision == "DENIED_VALIDATION"
    assert rows[0].client_id == "test-worker"
    assert rows[0].arguments["amount"] == over_limit_amount


@pytest.mark.asyncio
async def test_tool_call_without_allowlisted_tool_is_denied_and_audited(db_engine):
    """A client without the tool on its allowlist is rejected and audited,
    even with a valid token."""
    restricted_registry = ClientRegistry.from_records(
        [
            {
                "client_id": "restricted-worker",
                "token_hash": VALID_TOKEN_HASH,
                "allowed_tools": ["validate_fraud_score"],
            }
        ]
    )
    session_maker = get_session_maker(db_engine)
    app = create_app(registry=restricted_registry, session_maker=session_maker)
    transport = ASGITransport(app=app)

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "execute_refund",
            "arguments": {"transaction_id": "txn-1", "amount": 10.0, "currency": "USD"},
        },
    }

    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        response = await client.post(
            "/messages/?session_id=00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            content=json.dumps(payload),
        )

    assert response.status_code == 403

    async with session_maker() as session:
        result = await session.execute(
            select(McpAuditLog).where(McpAuditLog.client_id == "restricted-worker")
        )
        rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].decision == "DENIED_UNAUTHORIZED"


def _refund_call_payload(transaction_id: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "execute_refund",
            "arguments": {"transaction_id": transaction_id, "amount": 10.0, "currency": "USD"},
        },
    }


async def _call_tool(client: AsyncClient, *, token: str, payload: dict) -> Response:
    return await client.post(
        "/messages/?session_id=00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
        content=json.dumps(payload),
    )


@pytest.mark.asyncio
async def test_tool_call_rate_limit_blocks_after_threshold_and_audits(db_engine):
    """The Nth+1 call to the same tool within the window is rejected (429)
    and audited, once a client has already made N calls."""
    session_maker = get_session_maker(db_engine)
    app = create_app(registry=_test_registry(), session_maker=session_maker, rate_limit_per_min=3)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        for i in range(3):
            response = await _call_tool(
                client, token=VALID_TOKEN, payload=_refund_call_payload(f"txn-{i}")
            )
            # No live SSE session behind this session_id, so an allowed call
            # 404s from the inner app -- what matters here is that it's NOT
            # rejected by the middleware itself (429).
            assert response.status_code != 429

        limited_response = await _call_tool(
            client, token=VALID_TOKEN, payload=_refund_call_payload("txn-over-limit")
        )

    assert limited_response.status_code == 429

    async with session_maker() as session:
        result = await session.execute(
            select(McpAuditLog).where(McpAuditLog.decision == "DENIED_RATE_LIMITED")
        )
        rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].client_id == "test-worker"
    assert rows[0].tool == "execute_refund"


@pytest.mark.asyncio
async def test_rate_limit_is_scoped_per_tool_at_http_layer(db_engine):
    """Maxing out the limit on one tool doesn't block a different tool for
    the same client."""
    session_maker = get_session_maker(db_engine)
    app = create_app(registry=_test_registry(), session_maker=session_maker, rate_limit_per_min=3)
    transport = ASGITransport(app=app)

    fraud_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "validate_fraud_score", "arguments": {"user_id": "user-1"}},
    }

    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        for i in range(3):
            await _call_tool(client, token=VALID_TOKEN, payload=_refund_call_payload(f"txn-{i}"))

        other_tool_response = await _call_tool(client, token=VALID_TOKEN, payload=fraud_payload)

    assert other_tool_response.status_code != 429


@pytest.mark.asyncio
async def test_rate_limit_is_scoped_per_client_at_http_layer(db_engine):
    """Maxing out the limit for one client doesn't block another client
    calling the same tool."""
    other_token = "second-worker-token"
    registry = ClientRegistry.from_records(
        [
            {
                "client_id": "test-worker",
                "token_hash": VALID_TOKEN_HASH,
                "allowed_tools": ["execute_refund", "validate_fraud_score"],
            },
            {
                "client_id": "second-worker",
                "token_hash": hashlib.sha256(other_token.encode("utf-8")).hexdigest(),
                "allowed_tools": ["execute_refund"],
            },
        ]
    )
    session_maker = get_session_maker(db_engine)
    app = create_app(registry=registry, session_maker=session_maker, rate_limit_per_min=3)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        for i in range(3):
            await _call_tool(client, token=VALID_TOKEN, payload=_refund_call_payload(f"txn-{i}"))

        other_client_response = await _call_tool(
            client, token=other_token, payload=_refund_call_payload("txn-other-client")
        )

    assert other_client_response.status_code != 429
