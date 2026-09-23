"""The worker's AMQP helpers must survive a RabbitMQ restart instead of crashing
the process (found by tests/performance/chaos_idempotency.py)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiormq.exceptions import (
    AMQPConnectionError,
    ChannelClosed,
    ChannelInvalidStateError,
)

from src.worker.amqp import connect_with_retry, safe_ack, safe_nack


def _message(*, ack_error: Exception | None = None, nack_error: Exception | None = None) -> MagicMock:
    message = MagicMock()
    message.ack = AsyncMock(side_effect=ack_error)
    message.nack = AsyncMock(side_effect=nack_error)
    return message


@pytest.mark.asyncio
async def test_safe_ack_acks() -> None:
    message = _message()

    assert await safe_ack(message) is True
    message.ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_ack_survives_a_closed_channel() -> None:
    """The broker never got the ack, so it redelivers the message; the
    request_id idempotency absorbs the redelivery. Crashing gains nothing."""
    message = _message(ack_error=ChannelInvalidStateError())

    assert await safe_ack(message) is False


@pytest.mark.asyncio
async def test_safe_nack_passes_requeue_and_survives_a_closed_channel() -> None:
    message = _message(nack_error=ChannelClosed())

    assert await safe_nack(message, requeue=False) is False
    message.nack.assert_awaited_once_with(requeue=False)


@pytest.mark.asyncio
async def test_safe_ack_does_not_hide_unrelated_errors() -> None:
    message = _message(ack_error=ValueError("bug"))

    with pytest.raises(ValueError):
        await safe_ack(message)


@pytest.mark.asyncio
async def test_connect_with_retry_waits_for_the_broker() -> None:
    connection = MagicMock()
    connect = AsyncMock(side_effect=[AMQPConnectionError(), ConnectionRefusedError(), connection])
    sleep = AsyncMock()

    result = await connect_with_retry("amqp://x", connect=connect, sleep=sleep)

    assert result is connection
    assert connect.await_count == 3
    assert [c.args[0] for c in sleep.await_args_list] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_connect_with_retry_caps_the_backoff() -> None:
    connect = AsyncMock(side_effect=[OSError()] * 6 + [MagicMock()])
    sleep = AsyncMock()

    await connect_with_retry("amqp://x", connect=connect, sleep=sleep, max_delay=5.0)

    assert [c.args[0] for c in sleep.await_args_list] == [1.0, 2.0, 4.0, 5.0, 5.0, 5.0]


@pytest.mark.asyncio
async def test_connect_with_retry_does_not_retry_configuration_errors() -> None:
    connect = AsyncMock(side_effect=ValueError("bad url"))

    with pytest.raises(ValueError):
        await connect_with_retry("not-a-url", connect=connect, sleep=AsyncMock())
    assert connect.await_count == 1
