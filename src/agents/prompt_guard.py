import structlog
from langchain_core.messages import HumanMessage

from src.agents.llm_factory import get_llm
from src.agents.token_usage import extract_usage
from src.core.config import settings

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

        usage = extract_usage(response)
        if usage is not None:
            logger.info("llm_token_usage", stage="prompt_guard", provider="groq", **usage)

        # Groq's Prompt Guard endpoint returns a bare malicious-probability
        # score (e.g. "0.9989"), not a label -- parse it as a float.
        output_text = str(response.content).strip()
        try:
            score = float(output_text)
        except ValueError:
            logger.error(
                "Prompt guard returned a non-numeric response, failing open.",
                raw_output=output_text,
            )
            return False

        threshold = settings.PROMPT_GUARD_THRESHOLD
        if score >= threshold:
            logger.warning("Prompt injection DETECTED!", score=score, threshold=threshold)
            return True

        logger.info("Input scan clear. No injection detected.", score=score, threshold=threshold)
        return False

    except Exception as e:  # noqa: BLE001 -- deliberate fail-open, error is logged
        logger.error("Failed to run prompt guard, failing open (safe) to prevent block.", error=str(e))
        # Fail-open if the guard service goes down, so we don't break the whole app.
        # Real production systems might fail-closed depending on risk tolerance.
        return False
