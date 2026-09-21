import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, SystemMessage

# We import the module that doesn't exist yet to trigger the red state
from src.agents.judge import _run_single_judge, evaluate_decision


@pytest.mark.asyncio
async def test_judge_approve():
    """Test that the judge parses an APPROVE verdict correctly."""
    mock_llm = AsyncMock()
    # Langchain chat models return an AIMessage
    mock_llm.ainvoke.return_value = AIMessage(
        content=json.dumps({"verdict": "APPROVE", "reason": "Action is within scope."})
    )
    
    with patch("src.agents.judge.get_llm", return_value=mock_llm):
        result = await evaluate_decision(
            action_name="execute_refund",
            action_args={"transaction_id": "123", "amount": 50.0},
            context={"user_id": "user1"}
        )
        
        assert result["verdict"] == "APPROVE"
        assert "reason" in result
        # Double Judge: judge1_gemini and judge2_groq each call ainvoke once.
        # Both approve here, so the Supreme Court cascade is never invoked.
        assert mock_llm.ainvoke.call_count == 2


@pytest.mark.asyncio
async def test_judge_reject():
    """Test that the judge parses a REJECT verdict correctly."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(
        content=json.dumps({"verdict": "REJECT", "reason": "Amount exceeds allowed limit."})
    )
    
    with patch("src.agents.judge.get_llm", return_value=mock_llm):
        result = await evaluate_decision(
            action_name="execute_refund",
            action_args={"transaction_id": "123", "amount": 50000.0},
            context={"user_id": "user1"}
        )
        
        assert result["verdict"] == "REJECT"
        # Both base judges reject, which escalates to the Supreme Court cascade judge
        # (also mocked here) for a final tie-break — the reason reflects that escalation.
        assert result["reason"] == (
            "Supreme Court Final Rejection: Amount exceeds allowed limit. "
            "(Base judges: REJECT/REJECT)"
        )
        # judge1_gemini + judge2_groq + the Supreme Court tie-breaker.
        assert mock_llm.ainvoke.call_count == 3


@pytest.mark.asyncio
async def test_run_single_judge_fails_closed_on_construction_error():
    """_run_single_judge must catch an LLM construction failure (e.g. a missing
    optional provider package) the same way it already catches an invocation
    failure. Regression test for the Phase 1.C postmortem: an unguarded
    get_llm(provider="groq", ...) call used to raise ImportError straight out
    of evaluate_decision() instead of failing safe to REJECT."""
    with patch(
        "src.agents.judge.get_llm",
        side_effect=ImportError("langchain-groq is not installed"),
    ):
        result = await _run_single_judge("groq", 0.0, [SystemMessage(content="x")], stage="judge2")

    assert result == {
        "verdict": "REJECT",
        "reason": "System Guardrail Error: langchain-groq is not installed",
    }


@pytest.mark.asyncio
async def test_judge_groq_construction_failure_does_not_crash_evaluate_decision():
    """Regression test for the Phase 1.C postmortem: a missing langchain-groq
    package must not crash evaluate_decision() with an uncaught ImportError
    that propagates out of the MCP session (the actual root cause documented
    in docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md).
    """

    def fake_get_llm(*, provider: str, temperature: float = 0.0, **_: object) -> AsyncMock:
        if provider == "groq":
            raise ImportError("langchain-groq is not installed")
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content=json.dumps({"verdict": "APPROVE", "reason": "Looks fine."})
        )
        return mock_llm

    with patch("src.agents.judge.get_llm", side_effect=fake_get_llm):
        result = await evaluate_decision(
            action_name="execute_refund",
            action_args={"transaction_id": "123", "amount": 50.0},
            context={"user_id": "user1"},
        )

    # Must return a well-formed verdict dict; must never raise ImportError.
    assert result["verdict"] in ("APPROVE", "REJECT")
    assert "reason" in result


@pytest.mark.asyncio
async def test_run_single_judge_logs_token_usage_when_present():
    """Cost measurement (PENDING.md Step 1): a response carrying
    usage_metadata must be logged via usage_logger for later cost
    calculation."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(
        content=json.dumps({"verdict": "APPROVE", "reason": "ok"}),
        usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    )

    with patch("src.agents.judge.get_llm", return_value=mock_llm), \
         patch("src.agents.judge.usage_logger") as mock_usage_logger:
        await _run_single_judge("gemini", 0.0, [SystemMessage(content="x")], stage="judge1")

    mock_usage_logger.info.assert_called_once_with(
        "llm_token_usage",
        stage="judge1",
        provider="gemini",
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
    )


@pytest.mark.asyncio
async def test_run_single_judge_does_not_log_usage_when_absent():
    """Every existing mocked judge response (a bare AIMessage(content=...))
    carries no usage_metadata -- must stay silent, not crash or log junk."""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(
        content=json.dumps({"verdict": "APPROVE", "reason": "ok"})
    )

    with patch("src.agents.judge.get_llm", return_value=mock_llm), \
         patch("src.agents.judge.usage_logger") as mock_usage_logger:
        await _run_single_judge("gemini", 0.0, [SystemMessage(content="x")], stage="judge1")

    mock_usage_logger.info.assert_not_called()
