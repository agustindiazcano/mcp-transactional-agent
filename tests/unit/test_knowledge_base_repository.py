"""Unit tests for src.core.repositories.knowledge_base_repository.

These test the query/insert *shape* against a mocked AsyncSession -- the
actual pgvector <=> cosine-distance ordering semantics are verified against
a real Postgres in tests/integration/test_knowledge_base_repository.py.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.repositories import knowledge_base_repository


def _make_session(*, scalars_return: list | None = None) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=scalars_return or [])
    execute_result = MagicMock()
    execute_result.scalars = MagicMock(return_value=scalars_result)
    session.execute = AsyncMock(return_value=execute_result)
    return session


@pytest.mark.asyncio
async def test_insert_chunk_adds_and_flushes_but_does_not_commit() -> None:
    session = _make_session()

    row = await knowledge_base_repository.insert_chunk(
        session,
        source="refund_policy.md",
        source_tier="official",
        content="Refunds within 30 days.",
        embedding=[0.1] * 768,
    )

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert row.source == "refund_policy.md"
    assert row.content == "Refunds within 30 days."


@pytest.mark.asyncio
async def test_find_most_similar_returns_empty_list_when_no_rows() -> None:
    session = _make_session(scalars_return=[])

    results = await knowledge_base_repository.find_most_similar(session, [0.1] * 768)

    assert results == []
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_most_similar_returns_rows_from_query() -> None:
    fake_row = MagicMock()
    fake_row.content = "Refunds within 30 days."
    session = _make_session(scalars_return=[fake_row])

    results = await knowledge_base_repository.find_most_similar(session, [0.1] * 768, limit=1)

    assert results == [fake_row]
