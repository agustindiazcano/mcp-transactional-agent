from typing import Any, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from src.core.config import settings

# Optional imports for various cloud providers
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    ChatGoogleGenerativeAI: Any = None  # type: ignore

try:
    from langchain_openai import ChatOpenAI  # type: ignore
except ImportError:
    ChatOpenAI: Any = None  # type: ignore

try:
    from langchain_google_vertexai import ChatVertexAI  # type: ignore
except ImportError:
    ChatVertexAI: Any = None  # type: ignore

try:
    from langchain_aws import ChatBedrock  # type: ignore
except ImportError:
    ChatBedrock: Any = None  # type: ignore

try:
    from langchain_groq import ChatGroq  # type: ignore
except ImportError:
    ChatGroq: Any = None  # type: ignore


def get_llm(provider: str | None = None, temperature: float = 0.7, model_name: str | None = None) -> BaseChatModel:
    """
    Factory function to instantiate the active LLM based on environment configuration.
    
    Args:
        provider: Override the default provider from settings (e.g., 'gemini', 'groq')
        temperature: Set the determinism of the model (default 0.7 for agents, 0.0 for judges)
        model_name: Optional override for the specific model to use.
    """
    if provider is None:
        provider = settings.LLM_PROVIDER
    provider = provider.lower().strip()

    if provider == "mock":
        # Returns a valid JSON matching what the LLM-as-a-Judge expects
        return FakeListChatModel(
            responses=['{"verdict": "APPROVE", "reason": "Mocked for local dev"}']
        )
        
    elif provider == "openai":
        if ChatOpenAI is None:
            raise ImportError("langchain-openai is not installed")
        return cast(BaseChatModel, ChatOpenAI(
            model="gpt-4o",
            api_key=settings.OPENAI_API_KEY,
            temperature=temperature
        ))
        
    elif provider == "vertex":
        if ChatVertexAI is None:
            raise ImportError("langchain-google-vertexai is not installed")
        # Ensure credentials are provided in the environment or ADC
        return cast(BaseChatModel, ChatVertexAI(
            model_name="gemini-1.5-pro",
            temperature=temperature
        ))
        
    elif provider == "gemini":
        if ChatGoogleGenerativeAI is None:
            raise ImportError("langchain-google-genai is not installed")
        return cast(BaseChatModel, ChatGoogleGenerativeAI(
            model="gemini-3.5-flash-lite",
            google_api_key=settings.GEMINI_API_KEY,
            temperature=temperature
        ))
        
    elif provider == "bedrock":
        if ChatBedrock is None:
            raise ImportError("langchain-aws is not installed")
        return cast(BaseChatModel, ChatBedrock(
            model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
            region_name="us-east-1",
            model_kwargs={"temperature": temperature}
        ))
        
    elif provider == "groq":
        if ChatGroq is None:
            raise ImportError("langchain-groq is not installed")
        
        target_model = model_name if model_name else "openai/gpt-oss-20b"
        
        return cast(BaseChatModel, ChatGroq(
            model=target_model,
            api_key=settings.GROQ_API_KEY,
            temperature=temperature
        ))
        
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
