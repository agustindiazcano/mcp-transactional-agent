"""Database access for `orders`.

Pure DB access only -- no HTTP calls here (CLAUDE.md: repositories are for
database access only). Backs the MCP `get_order` tool and the local seed
script.
"""
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Order


async def get_order(session: AsyncSession, order_id: str) -> Order | None:
    """Return the order with this `order_id`, or None if there is none."""
    result = await session.execute(select(Order).where(Order.order_id == order_id))
    return result.scalar_one_or_none()


async def insert_orders_if_absent(
    session: AsyncSession, orders: Sequence[dict[str, Any]]
) -> int:
    """Insert orders that don't exist yet; return how many were inserted.

    Each entry needs `order_id`, `user_id`, `amount`, `currency`, and may
    carry `created_at`. An existing `order_id` is left untouched, never
    overwritten, so re-running a seed is safe.
    """
    if not orders:
        return 0
    rows = [{**order, "amount": Decimal(str(order["amount"]))} for order in orders]
    stmt = (
        insert(Order)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[Order.order_id])
        .returning(Order.id)
    )
    inserted = (await session.execute(stmt)).scalars().all()
    await session.commit()
    return len(inserted)
