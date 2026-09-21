from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Dimension of the configured embeddings provider's output vectors. Default is
# Gemini's `gemini-embedding-001`, truncated from its native 3072 dims to 768
# via `output_dimensionality` — see Phase 1.D in README.md/CLAUDE.md for why
# this is provider-agnostic rather than fixed to AWS Bedrock Titan.
EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    """SQLAlchemy model for the transactions table.

    The primary key (request_id) is also covered by an explicit
    UniqueConstraint and a separate index so that concurrent INSERT
    attempts on the same request_id immediately raise IntegrityError,
    allowing workers to detect and discard duplicate processing without
    an additional SELECT.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_transactions_request_id"),
        Index("ix_transactions_request_id", "request_id"),
    )

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, default="PROCESSING", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class KnowledgeBase(Base):
    """Business-rule documents (refund/warranty policy text) available for
    RAG retrieval (Phase 1.D).

    `source_tier` and `updated_at` exist specifically to feed the Phase 2
    fuzzy layer's inputs later (source trust tier, document freshness) —
    see confidence/fuzzy_layer.py.
    """

    __tablename__ = "knowledge_base"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_tier: Mapped[str] = mapped_column(String, default="official", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
