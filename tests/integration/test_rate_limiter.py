from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text

from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.models import McpAuditLog
from src.mcp_server.security.rate_limiter import is_rate_limited


@pytest_asyncio.fixture
async def db_engine():
    engine = get_engine(settings.DATABASE_URL)
    yield engine
    # Never Base.metadata.drop_all(): see test_worker.py/test_database.py for
    # why -- only clear this file's own rows.
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE mcp_audit_logs RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_maker = get_session_maker(db_engine)
    async with session_maker() as session:
        yield session


async def _insert_audit_row(
    session, *, client_id: str, tool: str, decision: str, created_at: datetime
) -> None:
    row = McpAuditLog(
        client_id=client_id,
        tool=tool,
        arguments={},
        decision=decision,
        result="invoked",
        created_at=created_at,
    )
    session.add(row)
    await session.commit()


@pytest.mark.asyncio
async def test_under_limit_is_not_rate_limited(db_session):
    now = datetime.now(UTC)
    for _ in range(2):
        await _insert_audit_row(
            db_session, client_id="worker-a", tool="execute_refund", decision="ALLOWED", created_at=now
        )

    limited = await is_rate_limited(
        db_session, client_id="worker-a", tool="execute_refund", limit_per_min=3, now=now
    )

    assert limited is False


@pytest.mark.asyncio
async def test_at_limit_is_rate_limited(db_session):
    now = datetime.now(UTC)
    for _ in range(3):
        await _insert_audit_row(
            db_session, client_id="worker-a", tool="execute_refund", decision="ALLOWED", created_at=now
        )

    limited = await is_rate_limited(
        db_session, client_id="worker-a", tool="execute_refund", limit_per_min=3, now=now
    )

    assert limited is True


@pytest.mark.asyncio
async def test_counts_denied_rows_too(db_session):
    now = datetime.now(UTC)
    for _ in range(3):
        await _insert_audit_row(
            db_session,
            client_id="worker-a",
            tool="execute_refund",
            decision="DENIED_VALIDATION",
            created_at=now,
        )

    limited = await is_rate_limited(
        db_session, client_id="worker-a", tool="execute_refund", limit_per_min=3, now=now
    )

    assert limited is True


@pytest.mark.asyncio
async def test_rate_limit_is_scoped_per_tool(db_session):
    now = datetime.now(UTC)
    for _ in range(3):
        await _insert_audit_row(
            db_session, client_id="worker-a", tool="execute_refund", decision="ALLOWED", created_at=now
        )

    limited = await is_rate_limited(
        db_session, client_id="worker-a", tool="validate_fraud_score", limit_per_min=3, now=now
    )

    assert limited is False


@pytest.mark.asyncio
async def test_rate_limit_is_scoped_per_client(db_session):
    now = datetime.now(UTC)
    for _ in range(3):
        await _insert_audit_row(
            db_session, client_id="worker-a", tool="execute_refund", decision="ALLOWED", created_at=now
        )

    limited = await is_rate_limited(
        db_session, client_id="worker-b", tool="execute_refund", limit_per_min=3, now=now
    )

    assert limited is False


@pytest.mark.asyncio
async def test_rows_outside_the_window_are_excluded(db_session):
    now = datetime.now(UTC)
    old_enough_to_exclude = now - timedelta(seconds=61)
    for _ in range(3):
        await _insert_audit_row(
            db_session,
            client_id="worker-a",
            tool="execute_refund",
            decision="ALLOWED",
            created_at=old_enough_to_exclude,
        )

    limited = await is_rate_limited(
        db_session, client_id="worker-a", tool="execute_refund", limit_per_min=3, now=now
    )

    assert limited is False


@pytest.mark.asyncio
async def test_rows_just_inside_the_window_are_included(db_session):
    now = datetime.now(UTC)
    just_inside = now - timedelta(seconds=59)
    for _ in range(3):
        await _insert_audit_row(
            db_session, client_id="worker-a", tool="execute_refund", decision="ALLOWED", created_at=just_inside
        )

    limited = await is_rate_limited(
        db_session, client_id="worker-a", tool="execute_refund", limit_per_min=3, now=now
    )

    assert limited is True
