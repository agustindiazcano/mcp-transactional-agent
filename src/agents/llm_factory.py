
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from src.core.config import settings

# We will need to import ChatGroq if it was requested, but let's mock/stub it for now
# or we can assume langchain-groq is used.
try:
    from langchain_groq import ChatGroq  # type: ignore
except ImportError:
    ChatGroq = None

def get_llm() -> BaseChatModel:
    """
    Factory function to instantiate the active LLM provider.
    Switches provider based on the LLM_PROVIDER environment variable/setting.
    """
    provider = settings.LLM_PROVIDER.lower().strip()
    
    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            model="gemini-1.5-flash", 
            google_api_key=settings.GEMINI_API_KEY
        )
    elif provider == "groq":
        if ChatGroq is None:
            raise ImportError("langchain-groq is not installed")
        return ChatGroq(
            model="llama3-70b-8192",
            api_key=settings.GROQ_API_KEY
        )
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
