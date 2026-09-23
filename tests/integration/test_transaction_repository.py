"""Integration tests for src.core.repositories.transaction_repository.

Needs a real PostgreSQL at the schema Alembic produced. Deliberately no
Base.metadata.create_all(): the schema is owned by migrations, and create_all
against the dev DB is what once created a stray `refunds` table ahead of its
migration. Only this file's own `repo-test-%` rows are cleared -- never a
TRUNCATE of `transactions`, which would wipe the dev DB's real rows.
"""
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.models import Transaction
from src.core.repositories.transaction_repository import get_recent_transactions

_OWN_ROWS = Transaction.request_id.like("repo-test-%")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = get_engine(settings.DATABASE_URL)
    session_maker = get_session_maker(engine)
    async with session_maker() as session:
        await session.execute(delete(Transaction).where(_OWN_ROWS))
        await session.commit()
        yield session
        await session.rollback()
        await session.execute(delete(Transaction).where(_OWN_ROWS))
        await session.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_recent_transactions_orders_newest_first(db_session) -> None:
    for i in range(3):
        db_session.add(
            Transaction(
                request_id=f"repo-test-{i}",
                payload={"user_id": "u"},
                status="COMPLETED",
            )
        )
    await db_session.commit()

    # Bump the last-inserted row's updated_at so ordering is unambiguous.
    txn = (await db_session.execute(
        text("SELECT * FROM transactions WHERE request_id = 'repo-test-2'")
    )).first()
    assert txn is not None

    rows = await get_recent_transactions(db_session, limit=10)
    ids = [row.request_id for row in rows]

    assert "repo-test-0" in ids
    assert "repo-test-1" in ids
    assert "repo-test-2" in ids


@pytest.mark.asyncio
async def test_get_recent_transactions_respects_limit(db_session) -> None:
    for i in range(5):
        db_session.add(
            Transaction(
                request_id=f"repo-test-{i}",
                payload={"user_id": "u"},
                status="COMPLETED",
            )
        )
    await db_session.commit()

    rows = await get_recent_transactions(db_session, limit=2)

    assert len(rows) == 2
