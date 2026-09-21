"""Server-side argument-validation schemas for MCP tools (Phase 1.B).

`MCPSecurityMiddleware` (src/mcp_server/security/middleware.py) validates a
`tools/call` request's raw arguments against the matching model here, before
the call ever reaches the tool function or the MCP SDK's own (looser,
extra-fields-silently-ignored) per-parameter schema. This is what makes
"amount bounded by REFUND_MAX_AMOUNT" and "unknown fields rejected" hold
regardless of what the LLM produced (CLAUDE.md Section 5a-i, item 3).
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from src.core.config import settings


class Currency(str, Enum):
    """Currencies accepted by financial tools. Restricting to an enum (rather
    than a free-form string) is itself part of the argument-validation gate.
    """

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class ExecuteRefundArgs(BaseModel):
    """Business limits for `execute_refund`. `extra="forbid"` rejects any
    field the LLM adds beyond this contract outright, per CLAUDE.md."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1)
    amount: float = Field(gt=0, le=settings.REFUND_MAX_AMOUNT)
    currency: Currency = Currency.USD


class ValidateFraudScoreArgs(BaseModel):
    """Business limits for `validate_fraud_score`."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)


TOOL_ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "execute_refund": ExecuteRefundArgs,
    "validate_fraud_score": ValidateFraudScoreArgs,
}
