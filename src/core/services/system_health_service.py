"""System health checks for the Phase 4 dashboard's top strip.

HTTP calls live here, not in repositories/ (CLAUDE.md Section 6: no httpx
inside src/core/repositories/).
"""
import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings

logger = structlog.get_logger(__name__)


async def check_db(session: AsyncSession) -> bool:
    """Return True if a trivial query against Postgres succeeds."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        logger.warning("system_health_db_check_failed", error=str(e))
        return False
    return True


async def check_mcp() -> bool:
    """Return True if the MCP server is reachable.

    A bare GET with no bearer token is expected to be rejected with 401 by
    MCPSecurityMiddleware (src/mcp_server/security/middleware.py) -- that
    401 is itself proof the server is alive and correctly enforcing the
    Phase 1.B security boundary, so it counts as healthy.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(settings.MCP_SERVER_URL)
    except httpx.HTTPError as e:
        logger.warning("system_health_mcp_check_failed", error=str(e))
        return False
    return response.status_code == 401
