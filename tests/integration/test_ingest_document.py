"""Integration test for ingest_document against a real Postgres + pgvector:
re-ingesting a document must replace its chunks, not duplicate them.

Duplicates would crowd the top-k retrieval results with copies of the same
text, and a Cloud Run ingest job re-run after a partial failure would plant
them. Uses LangChain's DeterministicFakeEmbedding, so no API key is needed.
"""
import pytest
import pytest_asyncio
from langchain_core.embeddings import DeterministicFakeEmbedding
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.services.retrieval_service import ingest_document

DIM = 768


@pytest_asyncio.fixture
async def db_engine():
    engine = get_engine(settings.DATABASE_URL)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE knowledge_base RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    async with get_session_maker(db_engine)() as session:
        yield session


async def _contents_by_source(session: AsyncSession) -> list[tuple[str, str]]:
    rows = await session.execute(
        text("SELECT source, content FROM knowledge_base ORDER BY source, content")
    )
    return [(r.source, r.content) for r in rows]


@pytest.mark.asyncio
async def test_reingesting_a_document_replaces_its_chunks(db_session: AsyncSession) -> None:
    embeddings = DeterministicFakeEmbedding(size=DIM)

    await ingest_document(
        db_session, embeddings, source="policy.md", source_tier="official",
        chunks=["old one", "old two"],
    )
    count = await ingest_document(
        db_session, embeddings, source="policy.md", source_tier="official",
        chunks=["new one", "new two"],
    )

    assert count == 2
    assert await _contents_by_source(db_session) == [
        ("policy.md", "new one"),
        ("policy.md", "new two"),
    ]


@pytest.mark.asyncio
async def test_reingesting_leaves_other_sources_untouched(db_session: AsyncSession) -> None:
    embeddings = DeterministicFakeEmbedding(size=DIM)

    await ingest_document(
        db_session, embeddings, source="other.md", source_tier="official", chunks=["keep me"],
    )
    await ingest_document(
        db_session, embeddings, source="policy.md", source_tier="official", chunks=["a"],
    )
    await ingest_document(
        db_session, embeddings, source="policy.md", source_tier="official", chunks=["a"],
    )

    assert await _contents_by_source(db_session) == [
        ("other.md", "keep me"),
        ("policy.md", "a"),
    ]
