import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.models import Transaction


@pytest_asyncio.fixture
async def db_engine():
    """Engine on the isolated test database (tests/conftest.py points
    settings.DATABASE_URL there), already migrated to head."""
    engine = get_engine(settings.DATABASE_URL)

    yield engine

    # Never Base.metadata.drop_all(): that drops every table on Base (including
    # tables other test files/the live app depend on), silently desyncing the
    # dev DB from alembic_version -- see the Phase 1.C postmortem. Only clear
    # this file's own rows.
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE transactions RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Provide a database session."""
    async_session = get_session_maker(db_engine)
    async with async_session() as session:
        yield session


@pytest.mark.asyncio
async def test_create_and_read_transaction(db_session: AsyncSession):
    """
    Test that the Transaction model can be created and persisted,
    verifying the fields: request_id, payload, and status.
    """
    request_id = "req-12345"
    payload = {"amount": 100.0, "currency": "USD"}
    status = "PENDING"
    
    # Create a new transaction
    new_txn = Transaction(
        request_id=request_id,
        payload=payload,
        status=status
    )
    
    db_session.add(new_txn)
    await db_session.commit()
    
    # Query it back
    result = await db_session.execute(
        select(Transaction).where(Transaction.request_id == request_id)
    )
    saved_txn = result.scalar_one_or_none()
    
    assert saved_txn is not None
    assert saved_txn.request_id == request_id
    assert saved_txn.payload == payload
    assert saved_txn.status == status
