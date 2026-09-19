from pydantic import BaseModel, Field
from typing import Optional
from uuid import uuid4

class ClaimRequest(BaseModel):
    user_id: str
    claim_text: str
    request_id: str = Field(default_factory=lambda: str(uuid4()))
