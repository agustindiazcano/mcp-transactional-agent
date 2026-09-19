from uuid import uuid4

from pydantic import BaseModel, Field


class ClaimRequest(BaseModel):
    user_id: str
    claim_text: str
    request_id: str = Field(default_factory=lambda: str(uuid4()))
