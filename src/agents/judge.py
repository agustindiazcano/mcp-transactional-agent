import json
import logging
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.llm_factory import get_llm

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = """You are an independent LLM-as-a-Judge guardrail for a financial transaction system.
Your job is to evaluate a proposed action by the primary agent and determine if it should be APPROVED or REJECTED.

Evaluation Criteria:
1. Is the action within the agent's authorized scope?
2. Are the arguments well-formed and parseable?
3. Does the action comply with basic business rules (e.g. refunds cannot be excessively large or missing critical context)?

Respond strictly in valid JSON format with exactly these two keys:
{
    "verdict": "APPROVE" or "REJECT",
    "reason": "A human-readable explanation of your decision."
}
"""

async def evaluate_decision(action_name: str, action_args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluates a proposed action using the LLM-as-a-Judge pattern.
    Returns a dictionary with 'verdict' and 'reason'.
    """
    llm = get_llm()
    # If the LLM supports setting temperature, we'd ideally set it to 0.0 here,
    # but the factory handles the instantiation. We'll rely on the default or 
    # bind temperature=0.0 if supported. For safety, we just invoke it.
    
    user_prompt = (
        f"Proposed Action: {action_name}\n"
        f"Arguments: {json.dumps(action_args)}\n"
        f"Context: {json.dumps(context)}\n\n"
        f"Evaluate this proposed action based on the criteria."
    )
    
    messages = [
        SystemMessage(content=JUDGE_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt)
    ]
    
    try:
        response = await llm.ainvoke(messages)
        # Clean the response content if it contains markdown JSON blocks
        content = str(response.content).strip()
        content = content.removeprefix("```json")
        content = content.removesuffix("```")
            
        result = json.loads(content.strip())
        
        # Validate format
        if "verdict" not in result or result["verdict"] not in ["APPROVE", "REJECT"]:
            raise ValueError("Invalid verdict returned by judge.")
            
        return cast(dict[str, Any], result)
        
    except Exception as e:  # noqa: BLE001
        logger.error(f"Judge evaluation failed: {e}")
        # Fail safe: if the judge crashes or hallucinates, reject the action.
        return {
            "verdict": "REJECT",
            "reason": f"System Guardrail Error: {e!s}"
        }
