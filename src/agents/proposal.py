"""The Front-Desk's proposal schema (Phase 1.E, CLAUDE.md Section 5a-iv).

The primary agent never decides anything: it maps a claim's free text to
this structured, server-side-validated shape and nothing else. The
Back-Office re-validates every field before it reaches the Double Judge --
the same "never trust LLM output, validate server-side" doctrine the MCP
security boundary applies to tool arguments (Section 5a-i, item 3), now
applied to the agent's own proposed intent, the new input surface this
phase adds.

`extra="forbid"` rejects any field the LLM invents beyond this contract
outright, and the model-level check below rejects a proposal that mixes
intents -- e.g. `clarify` carrying a half-filled `order_id`, which is a
partial refund guess dressed up as a question, not a clarifying question.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.config import settings
from src.core.currency import Currency

ProposalIntent = Literal["refund", "clarify", "out_of_scope"]


class ClaimProposal(BaseModel):
    """A structured proposal from the Front-Desk LLM.

    `refund` requires `order_id`, `amount`, and `currency` together -- an
    agent that cannot fill all three should propose `clarify` instead of
    guessing one. `clarify` and `out_of_scope` carry no refund fields;
    `reason` holds the rationale for `refund`/`out_of_scope`, or the
    clarifying question itself for `clarify`.
    """

    model_config = ConfigDict(extra="forbid")

    intent: ProposalIntent
    order_id: str | None = Field(default=None, min_length=1)
    amount: float | None = Field(default=None, gt=0, le=settings.REFUND_MAX_AMOUNT)
    currency: Currency | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_refund_fields_match_intent(self) -> "ClaimProposal":
        refund_fields_present = self.order_id is not None or self.amount is not None or self.currency is not None

        if self.intent == "refund":
            missing = [
                name
                for name, value in (
                    ("order_id", self.order_id),
                    ("amount", self.amount),
                    ("currency", self.currency),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"intent='refund' requires {', '.join(missing)}; "
                    "propose intent='clarify' instead of a partial refund."
                )
        elif refund_fields_present:
            raise ValueError(
                f"intent={self.intent!r} must not carry order_id/amount/currency; "
                "use intent='refund' once all three are known."
            )

        return self
