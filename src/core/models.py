from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, Numeric, String, Text, UniqueConstraint, func
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
    judge_trail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class Refund(Base):
    """A refund actually executed by the MCP `execute_refund` tool.

    `request_id` is the idempotency key: its UNIQUE constraint is what makes
    a retried or redelivered tool call return the existing refund instead of
    recording a second one (see src/core/repositories/refund_repository.py).
    Deliberately no foreign key to `transactions`: the MCP server owns this
    ledger and must not depend on the worker's table to record a refund.
    """

    __tablename__ = "refunds"
    __table_args__ = (UniqueConstraint("request_id", name="uq_refunds_request_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String, nullable=False)
    transaction_id: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Order(Base):
    """A purchase, read by the MCP `get_order` / `get_refund_history` tools.

    The evidence a refund is checked against: a refund must not exceed the
    order's amount (CLAUDE.md Section 10). `refunds.transaction_id` holds
    the refunded order's `order_id`, which is how refund history is joined
    to a user. Read-only from the application's side; local sample rows come
    from scripts/seed_orders.py, never from a migration.
    """

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_orders_order_id"),
        Index("ix_orders_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class McpAuditLog(Base):
    """Immutable audit trail for every MCP tool-call attempt (Phase 1.B).

    Written by `src.mcp_server.security.middleware.MCPSecurityMiddleware`
    before a tool executes -- see CLAUDE.md Section 4's fail-closed directive:
    if this insert fails, the call is denied rather than allowed to proceed.
    Insert-only by convention (no code path updates or deletes a row); the
    deployment's DB role for the MCP server should grant INSERT/SELECT only.
    """

    __tablename__ = "mcp_audit_logs"
    __table_args__ = (
        Index("ix_mcp_audit_logs_client_id_tool_created_at", "client_id", "tool", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String, nullable=False)
    tool: Mapped[str | None] = mapped_column(String, nullable=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
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
