from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.config import settings
from src.core.database import get_engine
from src.core.models import Base


@pytest_asyncio.fixture
async def db_engine():
    engine = get_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_client(db_engine) -> AsyncGenerator[AsyncClient, None]:
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
async def test_system_health_reports_db_and_mcp_up(async_client: AsyncClient) -> None:
    # check_mcp does its own httpx call, which would collide with the test
    # client's own httpx.AsyncClient if patched at the class level (see
    # tests/unit/core/services/test_system_health_service.py for that case) --
    # here we only care that the router aggregates the service's booleans.
    with patch("src.api.routers.system.check_mcp", new=AsyncMock(return_value=True)):
        response = await async_client.get("/api/v1/system-health")

    assert response.status_code == 200
    data = response.json()
    assert data == {"gateway": True, "db": True, "mcp": True}


@pytest.mark.asyncio
async def test_system_health_reports_mcp_down(async_client: AsyncClient) -> None:
    with patch("src.api.routers.system.check_mcp", new=AsyncMock(return_value=False)):
        response = await async_client.get("/api/v1/system-health")

    assert response.status_code == 200
    data = response.json()
    assert data["mcp"] is False
    assert data["db"] is True
