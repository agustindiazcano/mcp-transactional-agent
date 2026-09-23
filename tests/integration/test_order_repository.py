"""Integration tests for the read side that backs the MCP evidence tools:
src.core.repositories.order_repository (orders) and the per-user refund
history in src.core.repositories.refund_repository. `refunds` has no
user_id: a refund's `transaction_id` is the order it refunded, so history
by user is a join through `orders`.
"""
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.models import Refund
from src.core.repositories.order_repository import get_order, insert_orders_if_absent
from src.core.repositories.refund_repository import (
    list_refunds_for_user,
    record_refund,
    summarize_refunds_for_user,
)

ORDERS = [
    {"order_id": "ord-a1", "user_id": "alice", "amount": 100.0, "currency": "USD"},
    {"order_id": "ord-a2", "user_id": "alice", "amount": 30.0, "currency": "EUR"},
    {"order_id": "ord-a3", "user_id": "alice", "amount": 20.0, "currency": "USD"},
    {"order_id": "ord-b1", "user_id": "bob", "amount": 55.0, "currency": "USD"},
]


@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = get_engine(settings.DATABASE_URL)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE orders, refunds RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async with get_session_maker(db_engine)() as db_session:
        await insert_orders_if_absent(db_session, ORDERS)
        yield db_session


@pytest.mark.asyncio
async def test_get_order_returns_the_order(session: AsyncSession) -> None:
    order = await get_order(session, "ord-a1")

    assert order is not None
    assert order.user_id == "alice"
    assert order.amount == Decimal("100.00")
    assert order.currency == "USD"


@pytest.mark.asyncio
async def test_get_order_returns_none_for_unknown_order(session: AsyncSession) -> None:
    assert await get_order(session, "ord-missing") is None


@pytest.mark.asyncio
async def test_insert_orders_if_absent_is_idempotent(session: AsyncSession) -> None:
    """Re-running the seed inserts nothing and never overwrites a row."""
    changed = [{**ORDERS[0], "amount": 999.0}]

    inserted = await insert_orders_if_absent(session, changed)

    assert inserted == 0
    order = await get_order(session, "ord-a1")
    assert order is not None and order.amount == Decimal("100.00")


@pytest.mark.asyncio
async def test_refund_history_is_scoped_to_the_user_and_newest_first(
    session: AsyncSession,
) -> None:
    await record_refund(session, request_id="r1", transaction_id="ord-a1", amount=40.0, currency="USD")
    await record_refund(session, request_id="r2", transaction_id="ord-a2", amount=30.0, currency="EUR")
    await record_refund(session, request_id="r3", transaction_id="ord-b1", amount=55.0, currency="USD")
    await record_refund(session, request_id="r4", transaction_id="ord-a3", amount=20.0, currency="USD")
    # Make ordering unambiguous: r1 oldest, r4 newest.
    now = datetime.now(UTC)
    for offset, request_id in enumerate(["r1", "r2", "r4"]):
        await session.execute(
            update(Refund)
            .where(Refund.request_id == request_id)
            .values(created_at=now - timedelta(days=10 - offset))
        )
    await session.commit()

    refunds = await list_refunds_for_user(session, "alice", limit=2)

    assert [r.request_id for r in refunds] == ["r4", "r2"]


@pytest.mark.asyncio
async def test_refund_summary_counts_all_and_totals_per_currency(session: AsyncSession) -> None:
    await record_refund(session, request_id="r1", transaction_id="ord-a1", amount=40.0, currency="USD")
    await record_refund(session, request_id="r2", transaction_id="ord-a2", amount=30.0, currency="EUR")
    await record_refund(session, request_id="r4", transaction_id="ord-a3", amount=20.0, currency="USD")
    await record_refund(session, request_id="r3", transaction_id="ord-b1", amount=55.0, currency="USD")

    count, totals = await summarize_refunds_for_user(session, "alice")

    assert count == 3
    assert totals == {"USD": Decimal("60.00"), "EUR": Decimal("30.00")}


@pytest.mark.asyncio
async def test_refund_summary_for_user_without_refunds(session: AsyncSession) -> None:
    assert await summarize_refunds_for_user(session, "nobody") == (0, {})
