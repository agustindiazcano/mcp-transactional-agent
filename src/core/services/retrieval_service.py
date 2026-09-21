"""Phase 1.D RAG orchestration: embed text, then delegate to the
knowledge_base repository for storage/retrieval.

This is the layer allowed to call an external embeddings API -- CLAUDE.md
keeps repositories DB-only and puts external HTTP/API calls in services or
agents instead.
"""
import logging

import structlog
from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repositories import knowledge_base_repository

logger = logging.getLogger(__name__)
usage_logger = structlog.get_logger("token_usage")


async def ingest_document(
    session: AsyncSession,
    embeddings_client: Embeddings,
    *,
    source: str,
    source_tier: str,
    chunks: list[str],
) -> int:
    """Embed and store each chunk, committing once at the end.

    Returns the number of chunks inserted (0 for an empty `chunks` list).
    """
    if not chunks:
        return 0

    vectors = await embeddings_client.aembed_documents(chunks)
    for chunk, vector in zip(chunks, vectors, strict=True):
        await knowledge_base_repository.insert_chunk(
            session,
            source=source,
            source_tier=source_tier,
            content=chunk,
            embedding=vector,
        )
    await session.commit()
    logger.info(f"Ingested {len(chunks)} chunks from {source} into knowledge_base")
    return len(chunks)


async def retrieve_relevant_policy(
    session: AsyncSession,
    embeddings_client: Embeddings,
    claim_text: str,
) -> str | None:
    """Embed `claim_text` and return the single most similar policy chunk's
    content, or None if `claim_text` is blank or the knowledge base is empty.
    """
    if not claim_text.strip():
        return None

    vector = await embeddings_client.aembed_query(claim_text)

    # LangChain's Embeddings interface exposes no real token usage, unlike
    # chat models' AIMessage.usage_metadata -- this is a ~4-chars/token
    # estimate for cost tracking, not a metered figure (estimated=True).
    estimated_tokens = len(claim_text) // 4
    usage_logger.info(
        "llm_token_usage",
        stage="retrieval_embedding",
        provider="gemini",
        input_tokens=estimated_tokens,
        output_tokens=0,
        total_tokens=estimated_tokens,
        estimated=True,
    )

    matches = await knowledge_base_repository.find_most_similar(session, vector, limit=1)
    if not matches:
        return None
    return matches[0].content
