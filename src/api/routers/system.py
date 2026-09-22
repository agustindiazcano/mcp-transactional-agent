"""Aggregate system health for the Phase 4 dashboard's top strip.

The dashboard never calls Postgres or the MCP server directly -- it reads
this one endpoint, which does those checks server-side, per CLAUDE.md
Section 5d's API-consumer constraint.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session
from src.api.schemas import SystemHealth
from src.core.services.system_health_service import check_db, check_mcp

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/system-health", response_model=SystemHealth)
async def system_health(session: AsyncSession = Depends(get_db_session)) -> SystemHealth:  # noqa: B008
    db_ok = await check_db(session)
    mcp_ok = await check_mcp()
    return SystemHealth(db=db_ok, mcp=mcp_ok)
