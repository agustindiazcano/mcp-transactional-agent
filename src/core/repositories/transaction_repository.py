"""Database access for the `transactions` table.

Pure DB access only -- no HTTP calls here (CLAUDE.md: repositories are for
database access only; external calls belong in services/agents). Backs the
Phase 4 dashboard's read-only transaction list.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Transaction


async def get_recent_transactions(session: AsyncSession, *, limit: int = 50) -> list[Transaction]:
    """Return the `limit` most recently updated transactions, newest first."""
    stmt = select(Transaction).order_by(Transaction.updated_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
