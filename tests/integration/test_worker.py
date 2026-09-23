from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.prompt_guard import GuardResult
from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.models import Base, Transaction
from src.worker.worker import process_message


@pytest_asyncio.fixture
async def db_engine():
    engine = get_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
    session_maker = get_session_maker(db_engine)
    async with session_maker() as session:
        yield session

@pytest.mark.asyncio
async def test_worker_idempotency_new_request(db_session: AsyncSession):
    """Test that a new request creates a Transaction and processes it."""
    request_id = "test-req-new-123"
    
    from sqlalchemy import delete
    # Ensure it doesn't exist
    await db_session.execute(delete(Transaction).where(Transaction.request_id == request_id))
    await db_session.commit()
    
    # Mock message
    mock_message = AsyncMock()
    mock_message.body = b'{"request_id": "test-req-new-123", "user_id": "user1", "claim_text": "Refund $50"}'
    
    from contextlib import asynccontextmanager
    
    @asynccontextmanager
    async def mock_sse_client(*args, **kwargs):
        yield (AsyncMock(), AsyncMock())
        
    @asynccontextmanager
    async def mock_client_session(*args, **kwargs):
        session = AsyncMock()
        yield session

    # We mock the LLM factory, MCP execution, and Judge
    with patch("src.worker.worker.get_llm") as _, \
         patch("src.worker.worker.sse_client", new=mock_sse_client), \
         patch("src.worker.worker.ClientSession", new=mock_client_session), \
         patch("src.worker.worker.evaluate_decision", return_value={"verdict": "APPROVE", "reason": "Ok"}) as MockJudge:
             
        # Execute worker process
        await process_message(mock_message, db_session)
        
        # Verify ack was called
        mock_message.ack.assert_called_once()
        MockJudge.assert_called_once()
        
        # Verify transaction status
        result = await db_session.execute(select(Transaction).where(Transaction.request_id == request_id))
        txn = result.scalar_one_or_none()
        assert txn is not None
        assert txn.status == "COMPLETED"

@pytest.mark.asyncio
async def test_worker_persists_judge_trail(db_session: AsyncSession):
    """Phase 4 dashboard needs a real per-judge reasoning trail on the row,
    not just the aggregate status -- verify evaluate_decision()'s 'trail'
    ends up on Transaction.judge_trail after processing."""
    request_id = "test-req-trail-123"

    from sqlalchemy import delete
    await db_session.execute(delete(Transaction).where(Transaction.request_id == request_id))
    await db_session.commit()

    mock_message = AsyncMock()
    mock_message.body = b'{"request_id": "test-req-trail-123", "user_id": "user1", "claim_text": "Refund $50"}'

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_sse_client(*args, **kwargs):
        yield (AsyncMock(), AsyncMock())

    @asynccontextmanager
    async def mock_client_session(*args, **kwargs):
        session = AsyncMock()
        yield session

    fake_trail = {
        "judge1": {"verdict": "APPROVE", "reason": "Gemini ok"},
        "judge2": {"verdict": "APPROVE", "reason": "Groq ok"},
        "supreme_court": None,
    }

    clear_guard = GuardResult(status="clear", score=0.001)

    with patch("src.worker.worker.get_llm") as _, \
         patch("src.worker.worker.scan_for_injection", return_value=clear_guard), \
         patch("src.worker.worker.sse_client", new=mock_sse_client), \
         patch("src.worker.worker.ClientSession", new=mock_client_session), \
         patch(
             "src.worker.worker.evaluate_decision",
             return_value={"verdict": "APPROVE", "reason": "Ok", "trail": fake_trail},
         ):
        await process_message(mock_message, db_session)

        result = await db_session.execute(select(Transaction).where(Transaction.request_id == request_id))
        txn = result.scalar_one_or_none()
        assert txn is not None
        assert txn.judge_trail == {
            **fake_trail,
            "prompt_guard": {"status": "clear", "score": 0.001, "reason": None},
        }

@pytest.mark.asyncio
async def test_worker_judge_reject(db_session: AsyncSession):
    """Test that if the judge REJECTS the action, status is PENDING_HUMAN_REVIEW."""
    request_id = "test-req-reject-123"
    
    from sqlalchemy import delete
    await db_session.execute(delete(Transaction).where(Transaction.request_id == request_id))
    await db_session.commit()
    
    mock_message = AsyncMock()
    mock_message.body = b'{"request_id": "test-req-reject-123", "user_id": "user1", "claim_text": "Refund $50000"}'
    
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def mock_sse_client(*args, **kwargs):
        yield (AsyncMock(), AsyncMock())
        
    @asynccontextmanager
    async def mock_client_session(*args, **kwargs):
        session = AsyncMock()
        yield session

    with patch("src.worker.worker.get_llm") as _, \
         patch("src.worker.worker.sse_client", new=mock_sse_client), \
         patch("src.worker.worker.ClientSession", new=mock_client_session), \
         patch("src.worker.worker.evaluate_decision", return_value={"verdict": "REJECT", "reason": "Amount too high"}) as MockJudge:
             
        await process_message(mock_message, db_session)

        mock_message.ack.assert_called_once()
        # The self-correction loop retries up to MAX_LLM_RETRIES times on a
        # REJECT verdict before giving up, so a judge that always rejects is
        # called that many times, not once.
        assert MockJudge.call_count == settings.MAX_LLM_RETRIES

        result = await db_session.execute(select(Transaction).where(Transaction.request_id == request_id))
        txn = result.scalar_one_or_none()
        assert txn is not None
        assert txn.status == "PENDING_HUMAN_REVIEW"

@pytest.mark.asyncio
async def test_worker_idempotency_existing_request(db_session: AsyncSession):
    """Test that an existing COMPLETED request is acked and skipped."""
    request_id = "test-req-existing-123"
    
    # Create existing transaction
    txn = Transaction(request_id=request_id, payload={"test": "data"}, status="COMPLETED")
    db_session.add(txn)
    await db_session.commit()
    
    # Mock message
    mock_message = AsyncMock()
    mock_message.body = b'{"request_id": "test-req-existing-123", "user_id": "user1", "claim_text": "Refund $50"}'
    
    with patch("src.worker.worker.get_llm") as MockGetLlm:
        await process_message(mock_message, db_session)
        
        # It should ack immediately without calling LLM
        mock_message.ack.assert_called_once()
        MockGetLlm.assert_not_called()
