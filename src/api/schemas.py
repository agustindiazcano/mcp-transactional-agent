from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.config import settings
from src.core.currency import Currency


class ClaimRequest(BaseModel):
    """A claim submitted to the gateway.

    The refund details are optional -- a free-text claim is still judged --
    but without both `order_id` and `amount` there is nothing to execute, so
    an approved claim lacking them routes to PENDING_HUMAN_REVIEW instead of
    COMPLETED. When present they carry the same limits the MCP boundary
    enforces, so an out-of-bounds refund fails here with a 422 rather than
    after the judges approve it.
    """

    user_id: str
    claim_text: str
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    order_id: str | None = Field(default=None, min_length=1)
    amount: float | None = Field(default=None, gt=0, le=settings.REFUND_MAX_AMOUNT)
    currency: Currency | None = None


class TransactionSummary(BaseModel):
    """Read-only view of a transaction row for the Phase 4 dashboard."""

    request_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    payload: dict[str, Any]
    judge_trail: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class SystemHealth(BaseModel):
    """Aggregate health snapshot for the dashboard's top strip.

    A response at all proves the gateway itself is alive.
    """

    gateway: bool = True
    db: bool
    mcp: bool
