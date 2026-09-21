"""One-off ingestion script for Phase 1.D RAG: reads a policy Markdown file,
chunks it, embeds each chunk via the configured embeddings provider
(default: Gemini `gemini-embedding-001`, truncated to 768 dims), and inserts
the vectors into `knowledge_base`.

Usage:
    python -m scripts.ingest_knowledge_base [path/to/policy.md] [--source-tier official]

Requires the pgvector migration (7da4609fe11c) applied first:
    alembic upgrade head
"""
import argparse
import asyncio
import logging
from pathlib import Path

from src.agents.llm_factory import get_embeddings
from src.core.config import settings
from src.core.database import get_engine, get_session_maker
from src.core.services.chunking import chunk_markdown
from src.core.services.retrieval_service import ingest_document

logger = logging.getLogger(__name__)

DEFAULT_POLICY_PATH = Path("docs/policies/refund_policy.md")


async def run(path: Path, source_tier: str) -> int:
    """Chunk, embed, and store `path`'s contents. Returns the chunk count."""
    text = path.read_text(encoding="utf-8")
    chunks = chunk_markdown(text)

    engine = get_engine(settings.DATABASE_URL)
    session_maker = get_session_maker(engine)
    embeddings_client = get_embeddings()

    try:
        async with session_maker() as session:
            return await ingest_document(
                session,
                embeddings_client,
                source=path.name,
                source_tier=source_tier,
                chunks=chunks,
            )
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Ingest a policy Markdown file into knowledge_base (Phase 1.D)."
    )
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--source-tier", default="official")
    args = parser.parse_args()

    count = asyncio.run(run(args.path, args.source_tier))
    logger.info(f"Done: inserted {count} chunks from {args.path}")


if __name__ == "__main__":
    main()
