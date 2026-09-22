from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ClaimRequest(BaseModel):
    user_id: str
    claim_text: str
    request_id: str = Field(default_factory=lambda: str(uuid4()))


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
