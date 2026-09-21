"""Integration test for the knowledge_base repository against a real
Postgres + pgvector, verifying the actual `<=>` cosine-distance ordering --
something a mocked AsyncSession (tests/unit/test_knowledge_base_repository.py)
cannot prove. Uses hand-crafted vectors, not a real embeddings provider, so
it needs no API key and asserts exact, deterministic ranking.
"""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.models import Base
from src.core.repositories import knowledge_base_repository

DIM = 768


def _unit_vector(hot_index: int) -> list[float]:
    """A one-hot 768-dim vector -- cosine distance between two one-hot
    vectors at different indices is always 1.0 (maximally dissimilar),
    and 0.0 against itself, making ranking unambiguous."""
    vec = [0.0] * DIM
    vec[hot_index] = 1.0
    return vec


@pytest_asyncio.fixture
async def db_engine():
    engine = get_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_maker = get_session_maker(db_engine)
    async with session_maker() as session:
        yield session


@pytest.mark.asyncio
async def test_find_most_similar_returns_nearest_by_cosine_distance(
    db_session: AsyncSession,
) -> None:
    query_vector = _unit_vector(0)

    # exact_match is identical to the query -> cosine distance 0.0 (nearest).
    exact_match = await knowledge_base_repository.insert_chunk(
        db_session,
        source="test.md",
        source_tier="official",
        content="Exact match chunk.",
        embedding=query_vector,
    )
    # far_match is orthogonal to the query -> cosine distance 1.0 (farthest).
    await knowledge_base_repository.insert_chunk(
        db_session,
        source="test.md",
        source_tier="official",
        content="Unrelated chunk.",
        embedding=_unit_vector(1),
    )
    await db_session.commit()

    results = await knowledge_base_repository.find_most_similar(
        db_session, query_vector, limit=1
    )

    assert len(results) == 1
    assert results[0].id == exact_match.id
    assert results[0].content == "Exact match chunk."


@pytest.mark.asyncio
async def test_find_most_similar_orders_multiple_results_nearest_first(
    db_session: AsyncSession,
) -> None:
    query_vector = _unit_vector(0)

    far = await knowledge_base_repository.insert_chunk(
        db_session, source="t.md", source_tier="official",
        content="far", embedding=_unit_vector(1),
    )
    near = await knowledge_base_repository.insert_chunk(
        db_session, source="t.md", source_tier="official",
        content="near", embedding=query_vector,
    )
    await db_session.commit()

    results = await knowledge_base_repository.find_most_similar(
        db_session, query_vector, limit=2
    )

    assert [r.id for r in results] == [near.id, far.id]
