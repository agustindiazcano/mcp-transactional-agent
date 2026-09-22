from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.core.config import settings
from src.core.services.system_health_service import check_db, check_mcp


@pytest.mark.asyncio
async def test_check_db_true_on_successful_query() -> None:
    mock_session = AsyncMock()
    mock_session.execute.return_value = None

    assert await check_db(mock_session) is True


@pytest.mark.asyncio
async def test_check_db_false_on_sqlalchemy_error() -> None:
    mock_session = AsyncMock()
    mock_session.execute.side_effect = SQLAlchemyError("connection lost")

    assert await check_db(mock_session) is False


@pytest.mark.asyncio
async def test_check_mcp_true_on_401() -> None:
    mock_response = httpx.Response(401, request=httpx.Request("GET", settings.MCP_SERVER_URL))

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        assert await check_mcp() is True


@pytest.mark.asyncio
async def test_check_mcp_false_on_unexpected_status() -> None:
    mock_response = httpx.Response(200, request=httpx.Request("GET", settings.MCP_SERVER_URL))

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        assert await check_mcp() is False


@pytest.mark.asyncio
async def test_check_mcp_false_on_connection_error() -> None:
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("refused")):
        assert await check_mcp() is False
