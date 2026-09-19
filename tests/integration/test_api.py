import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
from src.api.main import app

@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
@patch("src.api.main.aio_pika.connect_robust")
async def test_create_claim(mock_connect_robust, async_client):
    # Setup mock for aio_pika
    mock_connection = AsyncMock()
    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    
    mock_connect_robust.return_value = mock_connection
    mock_connection.channel.return_value = mock_channel
    mock_channel.default_exchange = mock_exchange
    
    payload = {
        "user_id": "user-123",
        "claim_text": "I want a refund for my delayed flight."
    }
    
    response = await async_client.post("/api/v1/claims", json=payload)
    
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "Accepted"
    assert "request_id" in data
    
    # Verify RabbitMQ was called
    mock_connect_robust.assert_called_once()
    mock_exchange.publish.assert_called_once()
    
    # Extract the published message
    published_message = mock_exchange.publish.call_args[0][0]
    routing_key = mock_exchange.publish.call_args[1].get("routing_key") or mock_exchange.publish.call_args[0][1]
    
    assert routing_key == "agent_tasks_queue"
    assert published_message.content_type == "application/json"
