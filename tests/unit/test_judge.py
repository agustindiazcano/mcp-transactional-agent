import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

# We import the module that doesn't exist yet to trigger the red state
from src.agents.judge import evaluate_decision


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
