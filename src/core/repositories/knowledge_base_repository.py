"""Database access for the `knowledge_base` table (Phase 1.D RAG retrieval).

Pure DB access only -- no embeddings/HTTP calls here (CLAUDE.md: repositories
are for database access only; external calls belong in services/agents).
Callers generate the embedding vector and pass it in.
"""
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import KnowledgeBase


async def insert_chunk(
    session: AsyncSession,
    *,
    source: str,
    source_tier: str,
    content: str,
    embedding: list[float],
) -> KnowledgeBase:
    """Add one embedded chunk to the knowledge base.

    Flushes but does not commit -- the caller controls the transaction
    boundary (see src/core/services/retrieval_service.py).
    """
    row = KnowledgeBase(
        source=source,
        source_tier=source_tier,
        content=content,
        embedding=embedding,
    )
    session.add(row)
    await session.flush()
    return row


async def delete_by_source(session: AsyncSession, source: str) -> int:
    """Delete every chunk ingested from `source`. Returns how many were removed.

    Does not commit -- re-ingestion deletes and re-inserts under one commit, so
    a failure mid-way rolls back to the previous version of the document.
    """
    # A DELETE returns a CursorResult at runtime; execute() is typed as the generic Result.
    result = cast(
        CursorResult[Any],
        await session.execute(delete(KnowledgeBase).where(KnowledgeBase.source == source)),
    )
    return result.rowcount


async def find_most_similar(
    session: AsyncSession,
    embedding: list[float],
    *,
    limit: int = 1,
) -> list[KnowledgeBase]:
    """Return the `limit` rows nearest to `embedding` by cosine distance.

    Uses pgvector's `<=>` cosine-distance operator via the `cosine_distance`
    comparator -- not `<->` (l2_distance / Euclidean), which is a different
    metric and would rank matches differently.
    """
    stmt = (
        select(KnowledgeBase)
        .order_by(KnowledgeBase.embedding.cosine_distance(embedding))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
