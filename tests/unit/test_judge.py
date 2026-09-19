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
        mock_llm.ainvoke.assert_called_once()


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
        assert result["reason"] == "Amount exceeds allowed limit."
        mock_llm.ainvoke.assert_called_once()
