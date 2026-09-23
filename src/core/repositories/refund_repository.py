"""Database access for the `refunds` ledger.

Pure DB access only -- no HTTP calls here (CLAUDE.md: repositories are for
database access only). Backs the MCP `execute_refund` tool and the per-user
refund history behind `get_refund_history`. `refunds` has no user_id: a
refund's `transaction_id` is the order it refunded, so history by user is a
join through `orders`.
"""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Order, Refund


async def record_refund(
    session: AsyncSession,
    *,
    request_id: str,
    transaction_id: str,
    amount: float,
    currency: str,
) -> tuple[Refund, bool]:
    """Record a refund at most once per `request_id`.

    Returns `(refund, created)`. When a refund for `request_id` already
    exists, nothing is written and the stored row is returned with
    `created=False` -- even if the replayed arguments differ, since a replay
    must never change what was actually refunded. INSERT ... ON CONFLICT DO
    NOTHING makes this safe under concurrent calls too: exactly one INSERT
    wins, without an application-level lock.
    """
    stmt = (
        insert(Refund)
        .values(
            request_id=request_id,
            transaction_id=transaction_id,
            amount=Decimal(str(amount)),
            currency=currency,
        )
        .on_conflict_do_nothing(index_elements=[Refund.request_id])
        .returning(Refund.id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    await session.commit()

    refund = (
        await session.execute(select(Refund).where(Refund.request_id == request_id))
    ).scalar_one()
    return refund, inserted_id is not None


async def list_refunds_for_user(
    session: AsyncSession, user_id: str, *, limit: int
) -> list[Refund]:
    """Return up to `limit` refunds on `user_id`'s orders, newest first."""
    stmt = (
        select(Refund)
        .join(Order, Order.order_id == Refund.transaction_id)
        .where(Order.user_id == user_id)
        .order_by(Refund.created_at.desc(), Refund.id.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def summarize_refunds_for_user(
    session: AsyncSession, user_id: str
) -> tuple[int, dict[str, Decimal]]:
    """Return `(count, totals_by_currency)` over all of `user_id`'s refunds.

    Totals are per currency, never summed across currencies.
    """
    stmt = (
        select(Refund.currency, func.count(Refund.id), func.sum(Refund.amount))
        .join(Order, Order.order_id == Refund.transaction_id)
        .where(Order.user_id == user_id)
        .group_by(Refund.currency)
    )
    rows = (await session.execute(stmt)).all()
    count = sum(int(row[1]) for row in rows)
    totals = {str(row[0]): Decimal(row[2]) for row in rows}
    return count, totals
