"""Integration tests for src.core.repositories.refund_repository.

`request_id` is the refund's idempotency key: a retried `execute_refund`
call (worker retry, redelivered message, Recovery Sweeper requeue) must
return the refund that already exists instead of recording a second one.
Needs a real PostgreSQL, since the guarantee comes from the UNIQUE
constraint and ON CONFLICT, not from application code.
"""
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.models import Base, Refund
from src.core.repositories.refund_repository import record_refund


@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = get_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    # Never Base.metadata.drop_all() -- see test_worker.py. Only clear this
    # file's own rows.
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE refunds RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async with get_session_maker(db_engine)() as session:
        yield session


@pytest.mark.asyncio
async def test_first_call_records_refund(db_session: AsyncSession) -> None:
    refund, created = await record_refund(
        db_session,
        request_id="req-repo-1",
        transaction_id="ord-1",
        amount=50.25,
        currency="USD",
    )

    assert created is True
    assert refund.request_id == "req-repo-1"
    assert refund.transaction_id == "ord-1"
    assert refund.amount == Decimal("50.25")
    assert refund.currency == "USD"


@pytest.mark.asyncio
async def test_repeated_request_id_returns_existing_refund(db_session: AsyncSession) -> None:
    first, _ = await record_refund(
        db_session, request_id="req-repo-2", transaction_id="ord-2", amount=10.0, currency="EUR"
    )
    second, created = await record_refund(
        db_session, request_id="req-repo-2", transaction_id="ord-2", amount=10.0, currency="EUR"
    )

    assert created is False
    assert second.id == first.id

    count = await db_session.scalar(
        select(func.count()).select_from(Refund).where(Refund.request_id == "req-repo-2")
    )
    assert count == 1


@pytest.mark.asyncio
async def test_replay_with_different_args_returns_the_original_refund(
    db_session: AsyncSession,
) -> None:
    """A replay can never change what was refunded: the stored row wins."""
    await record_refund(
        db_session, request_id="req-repo-3", transaction_id="ord-3", amount=10.0, currency="USD"
    )
    replay, created = await record_refund(
        db_session, request_id="req-repo-3", transaction_id="ord-3", amount=9999.0, currency="USD"
    )

    assert created is False
    assert replay.amount == Decimal("10.00")
