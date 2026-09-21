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

async def _run_single_judge(llm: Any, messages: list[Any]) -> dict[str, Any]:
    try:
        response = await llm.ainvoke(messages)
        content_raw = response.content
        
        # Handle new LangChain format where content might be a list of blocks
        if isinstance(content_raw, list):
            content = "".join([
                block.get("text", "") if isinstance(block, dict) else str(block) 
                for block in content_raw
            ])
        else:
            content = str(content_raw)
            
        content = content.strip()
        
        # Extract JSON block using regex to handle variations in markdown formatting
        import re
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            content = match.group(0)
            
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON. Raw LLM output: {response.content}")
            raise
        
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

async def evaluate_decision(action_name: str, action_args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluates a proposed action using the Double LLM-as-a-Judge pattern.
    Returns a dictionary with 'verdict' and 'reason'.
    """
    import asyncio
    
    # Instantiate the two strict judges (temperature=0.0 for determinism)
    judge1_gemini = get_llm(provider="gemini", temperature=0.0)
    judge2_groq = get_llm(provider="groq", temperature=0.0)
    
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
    
    # Run both judges concurrently
    results = await asyncio.gather(
        _run_single_judge(judge1_gemini, messages),
        _run_single_judge(judge2_groq, messages),
        return_exceptions=True
    )
    
    res1, res2 = results
    
    if isinstance(res1, BaseException):
        res1 = {"verdict": "REJECT", "reason": f"Gemini Judge Exception: {res1!s}"}
    if isinstance(res2, BaseException):
        res2 = {"verdict": "REJECT", "reason": f"Groq Judge Exception: {res2!s}"}
        
    v1 = res1.get("verdict")
    v2 = res2.get("verdict")
    
    if v1 == "APPROVE" and v2 == "APPROVE":
        return {"verdict": "APPROVE", "reason": "Approved by both Gemini and Groq (GPT-OSS)."}
    else:
        logger.warning(f"Double Judge REJECT or disagreement detected (Gemini={v1}, Groq={v2}). Escalating to Supreme Court Judge...")
        try:
            # Supreme Court tie-breaker
            supreme_judge = get_llm(provider="gemini", temperature=0.0)
            supreme_res = await _run_single_judge(supreme_judge, messages)
            sv = supreme_res.get("verdict")
            
            if sv == "APPROVE":
                return {
                    "verdict": "APPROVE", 
                    "reason": f"Supreme Court Override: {supreme_res.get('reason')} (Base judges initially rejected/disagreed)"
                }
            else:
                return {
                    "verdict": "REJECT",
                    "reason": f"Supreme Court Final Rejection: {supreme_res.get('reason')} (Base judges: {v1}/{v2})"
                }
        except Exception as e:
            logger.error(f"Supreme Court failed or API key missing, falling back to base judges: {e}")
            reasons = []
            if v1 == "REJECT":
                reasons.append(f"Gemini: {res1.get('reason')}")
            if v2 == "REJECT":
                reasons.append(f"Groq: {res2.get('reason')}")
                
            return {
                "verdict": "REJECT",
                "reason": " | ".join(reasons)
            }
