"""AMQP helpers that keep the worker alive across a RabbitMQ restart.

Found by the chaos/idempotency test (tests/performance/chaos_idempotency.py):
when the broker restarted mid-message, ack() raised on the closed channel, the
error handler's nack() raised again, and the whole worker process died. On
restart, the first connect_robust() failed while the broker was still down, so
the process died again, and only Docker's bounded restart policy brought it back.

Settling a message on a dead channel is safe to skip: the broker never got the
ack, so it redelivers the message, and the request_id idempotency absorbs it.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from aiormq.exceptions import AMQPError, ChannelInvalidStateError

logger = logging.getLogger(__name__)

# Raised by ack()/nack() when the channel or its connection is gone.
CHANNEL_GONE_ERRORS: tuple[type[Exception], ...] = (ChannelInvalidStateError, AMQPError)
# Raised by connect() while the broker is unreachable.
BROKER_UNREACHABLE_ERRORS: tuple[type[Exception], ...] = (AMQPError, OSError)


async def safe_ack(message: Any) -> bool:  # Any: aio-pika message or a test double
    """Ack ``message``; return False if its channel is gone (it will be redelivered)."""
    try:
        await message.ack()
    except CHANNEL_GONE_ERRORS as exc:
        logger.warning(f"Ack not sent, channel closed ({exc!r}); the broker will redeliver.")
        return False
    return True


async def safe_nack(message: Any, *, requeue: bool) -> bool:  # Any: see safe_ack
    """Nack ``message``; return False if its channel is gone (it will be redelivered)."""
    try:
        await message.nack(requeue=requeue)
    except CHANNEL_GONE_ERRORS as exc:
        logger.warning(f"Nack not sent, channel closed ({exc!r}); the broker will redeliver.")
        return False
    return True


async def connect_with_retry(
    url: str,
    *,
    connect: Callable[[str], Awaitable[AbstractRobustConnection]] = aio_pika.connect_robust,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> AbstractRobustConnection:
    """Open a robust connection, waiting for the broker as long as it takes.

    connect_robust() reconnects on its own once connected, but its first connect
    fails immediately if the broker is down. This retries that first connect
    with capped exponential backoff instead of letting the process exit.
    """
    delay = base_delay
    while True:
        try:
            return await connect(url)
        except BROKER_UNREACHABLE_ERRORS as exc:
            logger.warning(f"RabbitMQ unreachable ({exc!r}); retrying in {delay:.0f}s.")
            await sleep(delay)
            delay = min(delay * 2, max_delay)
