from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from src.api.main import app
from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.models import Transaction


@pytest_asyncio.fixture
async def db_engine():
    engine = get_engine(settings.DATABASE_URL)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE transactions RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def async_client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    """Drives the app's real lifespan (which now also sets up the gateway's
    own DB engine/session-maker), with RabbitMQ mocked as in test_api.py."""
    with patch("src.api.main.aio_pika.connect_robust") as mock_connect_robust:
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_connect_robust.return_value = mock_connection
        mock_connection.channel.return_value = mock_channel

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client


@pytest.mark.asyncio
async def test_list_transactions_returns_recent_rows(async_client: AsyncClient, db_engine) -> None:
    session_maker = get_session_maker(db_engine)
    async with session_maker() as session:
        await session.execute(delete(Transaction).where(Transaction.request_id.like("dash-test-%")))
        await session.commit()

        session.add(
            Transaction(
                request_id="dash-test-1",
                payload={"user_id": "u1", "claim_text": "Refund $10"},
                status="COMPLETED",
                judge_trail={
                    "judge1": {"verdict": "APPROVE", "reason": "ok"},
                    "judge2": {"verdict": "APPROVE", "reason": "ok"},
                    "supreme_court": None,
                },
            )
        )
        await session.commit()

    response = await async_client.get("/api/v1/transactions", params={"limit": 10})

    assert response.status_code == 200
    rows = response.json()
    assert any(row["request_id"] == "dash-test-1" for row in rows)
    row = next(row for row in rows if row["request_id"] == "dash-test-1")
    assert row["status"] == "COMPLETED"
    assert row["judge_trail"]["judge1"]["verdict"] == "APPROVE"
    assert "created_at" in row
    assert "updated_at" in row


@pytest.mark.asyncio
async def test_list_transactions_respects_limit(async_client: AsyncClient, db_engine) -> None:
    session_maker = get_session_maker(db_engine)
    async with session_maker() as session:
        await session.execute(delete(Transaction).where(Transaction.request_id.like("dash-limit-%")))
        for i in range(5):
            session.add(
                Transaction(
                    request_id=f"dash-limit-{i}",
                    payload={"user_id": "u1", "claim_text": "x"},
                    status="COMPLETED",
                )
            )
        await session.commit()

    response = await async_client.get("/api/v1/transactions", params={"limit": 2})

    assert response.status_code == 200
    assert len(response.json()) == 2
