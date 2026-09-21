"""Unit tests for src.core.services.retrieval_service."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.services.retrieval_service import (
    ingest_document,
    retrieve_relevant_policy,
)


@pytest.mark.asyncio
async def test_ingest_document_with_no_chunks_is_a_noop() -> None:
    session = AsyncMock()
    embeddings_client = AsyncMock()

    count = await ingest_document(
        session, embeddings_client, source="x.md", source_tier="official", chunks=[]
    )

    assert count == 0
    embeddings_client.aembed_documents.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_document_embeds_inserts_each_chunk_and_commits_once() -> None:
    session = AsyncMock()
    embeddings_client = AsyncMock()
    chunks = ["chunk one", "chunk two"]
    embeddings_client.aembed_documents = AsyncMock(return_value=[[0.1] * 768, [0.2] * 768])

    with patch(
        "src.core.services.retrieval_service.knowledge_base_repository.insert_chunk",
        new_callable=AsyncMock,
    ) as mock_insert:
        count = await ingest_document(
            session, embeddings_client, source="x.md", source_tier="official", chunks=chunks
        )

    assert count == 2
    embeddings_client.aembed_documents.assert_awaited_once_with(chunks)
    assert mock_insert.await_count == 2
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_relevant_policy_returns_none_for_blank_claim() -> None:
    session = AsyncMock()
    embeddings_client = AsyncMock()

    result = await retrieve_relevant_policy(session, embeddings_client, "   ")

    assert result is None
    embeddings_client.aembed_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_relevant_policy_returns_none_when_knowledge_base_empty() -> None:
    session = AsyncMock()
    embeddings_client = AsyncMock()
    embeddings_client.aembed_query = AsyncMock(return_value=[0.1] * 768)

    with patch(
        "src.core.services.retrieval_service.knowledge_base_repository.find_most_similar",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await retrieve_relevant_policy(session, embeddings_client, "I want a refund")

    assert result is None


@pytest.mark.asyncio
async def test_retrieve_relevant_policy_returns_top_match_content() -> None:
    session = AsyncMock()
    embeddings_client = AsyncMock()
    embeddings_client.aembed_query = AsyncMock(return_value=[0.1] * 768)

    fake_row = MagicMock()
    fake_row.content = "Refunds within 30 days of purchase."

    with patch(
        "src.core.services.retrieval_service.knowledge_base_repository.find_most_similar",
        new_callable=AsyncMock,
        return_value=[fake_row],
    ):
        result = await retrieve_relevant_policy(session, embeddings_client, "I want a refund")

    assert result == "Refunds within 30 days of purchase."
    embeddings_client.aembed_query.assert_awaited_once_with("I want a refund")
