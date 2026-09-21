import structlog
from langchain_core.messages import HumanMessage

from src.agents.llm_factory import get_llm

logger = structlog.get_logger(__name__)

async def check_for_injection(user_input: str) -> bool:
    """
    Evaluates the user's input for Prompt Injections or Jailbreak attempts
    using Llama Prompt Guard 2 22M via Groq.
    
    Returns True if an injection is detected (unsafe), False otherwise.
    """
    try:
        # Deliberately hardcoded, not gated by LLM_PROVIDER: this is a static,
        # ultra-low-latency pre-execution shield and must not inherit the
        # provider configured for the heavy reasoning agent (segregation of
        # duties, not an oversight — see PENDING.md).
        guard_model = get_llm(
            provider="groq", 
            temperature=0.0, 
            model_name="meta-llama/llama-prompt-guard-2-22m"
        )
        
        # Prompt Guard is fine-tuned to classify text simply by receiving it
        # No system prompt is strictly necessary, it just outputs classification
        messages = [HumanMessage(content=user_input)]
        
        logger.info("Scanning input for prompt injection...", length=len(user_input))
        response = await guard_model.ainvoke(messages)
        
        output_text = str(response.content).strip().lower()
        
        # The model typically returns safe, unsafe, injection, or jailbreak
        if "unsafe" in output_text or "injection" in output_text or "jailbreak" in output_text:
            logger.warning("Prompt injection DETECTED!", classification=output_text)
            return True
            
        logger.info("Input scan clear. No injection detected.")
        return False

    except Exception as e:
        logger.error("Failed to run prompt guard, failing open (safe) to prevent block.", error=str(e))
        # Fail-open if the guard service goes down, so we don't break the whole app.
        # Real production systems might fail-closed depending on risk tolerance.
        return False
