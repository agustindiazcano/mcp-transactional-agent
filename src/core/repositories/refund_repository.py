"""Database access for the `refunds` ledger.

Pure DB access only -- no HTTP calls here (CLAUDE.md: repositories are for
database access only). Backs the MCP `execute_refund` tool.
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Refund


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
