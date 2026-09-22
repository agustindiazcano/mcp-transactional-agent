"""Shared FastAPI dependencies for API routing.

Wiring only (Separation of Concerns, CLAUDE.md Section 4) -- no business
logic or direct query construction here, that belongs in services/
repositories.
"""
from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped AsyncSession from the engine set up in main.py's
    lifespan (one engine per app lifetime, not one per request)."""
    session_maker = request.app.state.db_session_maker
    async with session_maker() as session:
        yield session
