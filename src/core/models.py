from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
