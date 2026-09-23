"""Load sample orders into `orders` for local development and demos.

Idempotent: an order_id already present is left untouched, so it is safe to
re-run. Sample data lives here, never in a migration, so the same migrations
can run against a real database without planting fake orders in it.

Usage:
    python -m scripts.seed_orders

Requires the orders migration (c4d2a7e81f35) applied first:
    alembic upgrade head
"""
import asyncio
import logging
from typing import Any

from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.repositories.order_repository import insert_orders_if_absent

logger = logging.getLogger(__name__)

# user-1 is the dashboard form's default user. The mix covers the cases the
# evidence checks care about: small and large orders, and several currencies.
SAMPLE_ORDERS: list[dict[str, Any]] = [
    {"order_id": "ord-1001", "user_id": "user-1", "amount": 45.50, "currency": "USD"},
    {"order_id": "ord-1002", "user_id": "user-1", "amount": 120.00, "currency": "USD"},
    {"order_id": "ord-1003", "user_id": "user-1", "amount": 19.99, "currency": "EUR"},
    {"order_id": "ord-2001", "user_id": "user-2", "amount": 899.00, "currency": "USD"},
    {"order_id": "ord-2002", "user_id": "user-2", "amount": 35.00, "currency": "GBP"},
    {"order_id": "ord-3001", "user_id": "user-3", "amount": 2500.00, "currency": "EUR"},
]


async def run() -> int:
    """Insert the sample orders that are missing. Returns how many were added."""
    engine = get_engine(settings.DATABASE_URL)
    try:
        async with get_session_maker(engine)() as session:
            return await insert_orders_if_absent(session, SAMPLE_ORDERS)
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    inserted = asyncio.run(run())
    logger.info("Done: inserted %d of %d sample orders", inserted, len(SAMPLE_ORDERS))


if __name__ == "__main__":
    main()
