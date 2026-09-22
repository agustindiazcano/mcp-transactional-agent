"""Read-only transaction listing for the Phase 4 dashboard.

The dashboard (src/ui/) never touches Postgres directly -- it consumes this
endpoint only, per CLAUDE.md Section 5d's API-consumer constraint.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session
from src.api.schemas import TransactionSummary
from src.core.repositories.transaction_repository import get_recent_transactions

router = APIRouter(prefix="/api/v1", tags=["transactions"])


@router.get("/transactions", response_model=list[TransactionSummary])
async def list_transactions(
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008 -- FastAPI DI idiom
) -> list[TransactionSummary]:
    rows = await get_recent_transactions(session, limit=limit)
    return [TransactionSummary.model_validate(row) for row in rows]
