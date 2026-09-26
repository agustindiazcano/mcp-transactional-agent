"""Tests for the promptfoo Front-Desk provider's pure helpers (evals/promptfoo).

Mirrors test_judge_provider.py: the provider must build messages and parse
replies through production's own functions (CLAUDE.md's Promptfoo rule --
grade production code, never a copy), and must fail closed to `clarify` the
same way `front_desk.py`'s `_propose()` does on a malformed or invalid reply.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "evals" / "promptfoo"))

import front_desk_provider


def test_front_desk_inputs_mirror_the_worker() -> None:
    messages = front_desk_provider.front_desk_messages(
        {"claim_text": "Refund my order please.", "request_id": "eval-1"}
    )

    assert "<untrusted_data>" in messages[1].content
    assert "Refund my order please." in messages[1].content


def test_front_desk_inputs_thread_rejection_feedback_when_given() -> None:
    messages = front_desk_provider.front_desk_messages(
        {
            "claim_text": "Refund my order please.",
            "request_id": "eval-1",
            "rejection_feedback": "Amount exceeds the order total.",
        }
    )

    assert "Amount exceeds the order total." in messages[1].content


async def _call_api_with_fake_llm(response_text: str) -> dict[str, Any]:
    fake_llm = AsyncMock()
    fake_llm.ainvoke = AsyncMock(return_value=AIMessage(content=response_text))
    with patch.object(front_desk_provider, "get_llm", return_value=fake_llm):
        return await front_desk_provider.call_api(
            "unused",
            {"config": {"provider": "mock"}},
            {"vars": {"claim_text": "Refund my order please.", "request_id": "eval-1"}},
        )


def test_call_api_returns_the_proposals_intent() -> None:
    result = asyncio.run(
        _call_api_with_fake_llm(
            '{"intent": "refund", "order_id": "ord-1", "amount": 25.0, '
            '"currency": "USD", "reason": "Customer asked for a refund."}'
        )
    )

    assert json.loads(result["output"])["intent"] == "refund"


def test_call_api_fails_closed_to_clarify_on_malformed_json() -> None:
    """A reply that can't be parsed counts as clarify, exactly as production's
    `_propose()` does -- not reported to promptfoo as an error."""
    result = asyncio.run(_call_api_with_fake_llm("not valid json"))

    assert json.loads(result["output"])["intent"] == "clarify"


def test_call_api_fails_closed_to_clarify_on_invalid_proposal_shape() -> None:
    result = asyncio.run(
        _call_api_with_fake_llm(
            '{"intent": "refund", "order_id": "ord-1", "reason": "Missing amount and currency."}'
        )
    )

    assert json.loads(result["output"])["intent"] == "clarify"


def test_call_api_reports_a_provider_error_to_promptfoo() -> None:
    fake_llm = AsyncMock()
    fake_llm.ainvoke = AsyncMock(side_effect=RuntimeError("provider is down"))
    with patch.object(front_desk_provider, "get_llm", return_value=fake_llm):
        result = asyncio.run(
            front_desk_provider.call_api(
                "unused",
                {"config": {"provider": "mock"}},
                {"vars": {"claim_text": "Refund my order please.", "request_id": "eval-1"}},
            )
        )

    assert "error" in result
