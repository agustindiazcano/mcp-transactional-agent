"""Background Recovery Sweeper for stale (zombie) transactions.

Runs as an independent process alongside the main worker. Patrols the
database every SWEEPER_INTERVAL_SECONDS and recovers PROCESSING rows that
have not been updated in SWEEPER_STALE_THRESHOLD_SECONDS — which indicates
the worker that claimed them crashed before completing.

Recovery strategy:
  1. SELECT stale rows WITH FOR UPDATE SKIP LOCKED
     (non-blocking; skips rows actively held by a live worker lock).
  2. DELETE the zombie row to clear the UniqueConstraint block.
  3. Re-publish the original payload to RabbitMQ so a fresh worker can
     claim it via a clean INSERT.

The Sweeper never touches the main Worker logic and must never be imported
from worker.py. It is started independently:

    python -m src.worker.recovery_sweeper
"""
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import aio_pika
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.models import Transaction

logger = logging.getLogger(__name__)


async def run_sweep(db_session: AsyncSession, channel: aio_pika.abc.AbstractChannel) -> None:
    """Execute a single sweep iteration.

    Finds all zombie PROCESSING rows older than SWEEPER_STALE_THRESHOLD_SECONDS,
    deletes each one, and re-publishes its payload to the RabbitMQ queue.

    Args:
        db_session: An active async SQLAlchemy session.
        channel: An open aio_pika channel for publishing recovered messages.
    """
    threshold = datetime.now(tz=UTC) - timedelta(
        seconds=settings.SWEEPER_STALE_THRESHOLD_SECONDS
    )

    # FOR UPDATE SKIP LOCKED: skip rows currently held by a live worker lock.
    # This prevents deadlocks when a legitimate worker is mid-flight on a row.
    result = await db_session.execute(
        select(Transaction)
        .where(Transaction.status == "PROCESSING")
        .where(Transaction.updated_at < threshold)
        .with_for_update(skip_locked=True)
    )
    zombie_rows = result.scalars().all()

    if not zombie_rows:
        logger.debug("Sweeper: no zombie transactions found.")
        await db_session.commit()
        return

    for txn in zombie_rows:
        logger.warning(
            f"Zombie transaction detected, recovering: {txn.request_id} "
            f"(stuck since {txn.updated_at.isoformat()})"
        )

        # 1. Delete clears the UniqueConstraint so a fresh worker can INSERT cleanly.
        await db_session.delete(txn)

        # 2. Re-publish the original payload to the queue.
        message = aio_pika.Message(
            json.dumps(txn.payload).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await channel.default_exchange.publish(
            message, routing_key="agent_tasks_queue"
        )
        logger.info(f"Recovered transaction {txn.request_id} requeued to agent_tasks_queue.")

    await db_session.commit()
    logger.info(f"Sweeper: recovered {len(zombie_rows)} zombie transaction(s).")


async def start_sweeper() -> None:
    """Main entry point: run the sweep loop indefinitely.

    Connects independently to PostgreSQL and RabbitMQ so that this process
    can be stopped/restarted without affecting running workers.
    """
    logger.info(
        f"Recovery Sweeper started. "
        f"Interval={settings.SWEEPER_INTERVAL_SECONDS}s, "
        f"StaleThreshold={settings.SWEEPER_STALE_THRESHOLD_SECONDS}s"
    )

    engine = get_engine(settings.DATABASE_URL)
    session_maker = get_session_maker(engine)
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)

    async with connection:
        channel = await connection.channel()

        while True:
            try:
                async with session_maker() as db_session:
                    await run_sweep(db_session, channel)
            except Exception as exc:  # noqa: BLE001
                # A sweeper failure must never crash the process or affect workers.
                logger.error(f"Sweeper iteration failed (will retry): {exc}")

            await asyncio.sleep(settings.SWEEPER_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_sweeper())
