import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.database import get_engine, get_session_maker
from src.core.models import Base, Transaction


@pytest.fixture
async def db_engine():
    """Create a test engine connected to the local test database."""
    # We assume a test DB is running or we just use SQLite in memory for this simple test,
    # but since we need pgvector eventually, we use asyncpg against the local postgres.
    # For test isolation, we'll connect to the default DB for the test.
    engine = get_engine("postgresql+asyncpg://postgres:password@localhost:5432/agentic_engine")
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        
    yield engine
    
    # Teardown
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
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
