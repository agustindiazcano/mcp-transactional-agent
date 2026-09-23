from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import aio_pika
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.main import app

CLAIM_PAYLOAD = {
    "user_id": "user-123",
    "claim_text": "I want a refund for my delayed flight."
}


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[tuple[AsyncClient, AsyncMock, AsyncMock], None]:
    """An AsyncClient with the app's real lifespan driven manually.

    httpx's ASGITransport does not run the ASGI lifespan protocol on its
    own, and this project has no asgi-lifespan dependency to add for it,
    so the lifespan context manager is entered directly via Starlette's
    own app.router.lifespan_context(app) — this is what actually opens
    the (mocked) RabbitMQ connection/channel onto app.state before any
    request is made, matching how a real ASGI server would drive it.
    """
    with patch("src.api.main.aio_pika.connect_robust") as mock_connect_robust:
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_connect_robust.return_value = mock_connection
        mock_connection.channel.return_value = mock_channel

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client, mock_connect_robust, mock_channel


@pytest.mark.asyncio
async def test_create_claim(async_client: tuple[AsyncClient, AsyncMock, AsyncMock]) -> None:
    client, mock_connect_robust, mock_channel = async_client

    response = await client.post("/api/v1/claims", json=CLAIM_PAYLOAD)

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "Accepted"
    assert "request_id" in data

    # RabbitMQ connection/channel are set up once, at startup (lifespan).
    mock_connect_robust.assert_called_once()
    mock_channel.default_exchange.publish.assert_called_once()

    # Extract the published message
    publish_call = mock_channel.default_exchange.publish.call_args
    published_message = publish_call[0][0]
    routing_key = publish_call[1].get("routing_key") or publish_call[0][1]

    assert routing_key == "agent_tasks_queue"
    assert published_message.content_type == "application/json"


@pytest.mark.asyncio
async def test_create_claim_reuses_connection_across_multiple_requests(
    async_client: tuple[AsyncClient, AsyncMock, AsyncMock],
) -> None:
    """Regression test: the postmortem's flagged bug was a brand-new
    aio_pika.connect_robust() connection (and a fresh channel + queue
    declare) on every single request. The connection/channel must now be
    created once, at startup, and reused across requests."""
    client, mock_connect_robust, mock_channel = async_client

    first = await client.post("/api/v1/claims", json=CLAIM_PAYLOAD)
    second = await client.post("/api/v1/claims", json=CLAIM_PAYLOAD)

    assert first.status_code == 202
    assert second.status_code == 202

    mock_connect_robust.assert_called_once()
    mock_connect_robust.return_value.channel.assert_called_once()
    assert mock_channel.default_exchange.publish.call_count == 2


@pytest.mark.asyncio
async def test_create_claim_publishes_a_persistent_message(
    async_client: tuple[AsyncClient, AsyncMock, AsyncMock],
) -> None:
    """A 202 promises the claim will be processed. The queue is durable, but a
    transient message in it is still dropped when RabbitMQ restarts, so the
    message itself must be persistent (found by the chaos/idempotency test)."""
    client, _, mock_channel = async_client

    response = await client.post("/api/v1/claims", json=CLAIM_PAYLOAD)

    assert response.status_code == 202
    published_message = mock_channel.default_exchange.publish.call_args[0][0]
    assert published_message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
