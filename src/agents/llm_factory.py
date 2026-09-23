import hashlib
from typing import Any, cast

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import SecretStr

from src.core.config import settings

# Optional imports for various cloud providers. OpenAI and Bedrock aren't
# declared dependencies; pyproject's [tool.mypy] overrides let mypy pass
# whether or not they're installed (they aren't in CI).
try:
    from langchain_google_genai import (
        ChatGoogleGenerativeAI,
        GoogleGenerativeAIEmbeddings,
    )
except ImportError:
    ChatGoogleGenerativeAI: Any = None  # type: ignore
    GoogleGenerativeAIEmbeddings: Any = None  # type: ignore

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI: Any = None  # type: ignore

try:
    from langchain_aws import ChatBedrock
except ImportError:
    ChatBedrock: Any = None  # type: ignore

try:
    from langchain_groq import ChatGroq
except ImportError:
    ChatGroq: Any = None  # type: ignore


# Groq-hosted Llama Prompt Guard; it answers with a bare malicious-probability
# score, not the judges' JSON, so the mock provider needs a response of its own.
PROMPT_GUARD_MODEL = "meta-llama/llama-prompt-guard-2-22m"


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
        if model_name == PROMPT_GUARD_MODEL:
            # A benign score, so the guard reports 'clear' instead of 'skipped'
            return FakeListChatModel(responses=["0.0"])
        # Returns a valid JSON matching what the LLM-as-a-Judge expects
        return FakeListChatModel(
            responses=['{"verdict": "APPROVE", "reason": "Mocked for local dev"}']
        )
        
    elif provider == "openai":
        if ChatOpenAI is None:
            raise ImportError("langchain-openai is not installed")
        return cast(BaseChatModel, ChatOpenAI(
            model="gpt-4o",
            api_key=SecretStr(settings.OPENAI_API_KEY),
            temperature=temperature
        ))
        
    elif provider == "vertex":
        if ChatGoogleGenerativeAI is None:
            raise ImportError("langchain-google-genai is not installed")
        # langchain-google-genai's Vertex backend (ChatVertexAI is deprecated).
        # Credentials come from ADC (the Cloud Run service account, or
        # GOOGLE_APPLICATION_CREDENTIALS locally) -- no API key.
        return cast(BaseChatModel, ChatGoogleGenerativeAI(
            model=settings.VERTEX_MODEL,
            vertexai=True,
            project=settings.VERTEX_PROJECT or None,
            location=settings.VERTEX_LOCATION,
            temperature=temperature,
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
            api_key=SecretStr(settings.GROQ_API_KEY),
            temperature=temperature
        ))
        
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


class _DeterministicHashEmbeddings(Embeddings):
    """Dependency-free deterministic embeddings for local dev/tests.

    Mirrors get_llm()'s 'mock' provider (no API spend). langchain_core's own
    fake embeddings (DeterministicFakeEmbedding) require numpy, which is not
    a project dependency, so this hand-rolled version uses only hashlib.
    Vectors are stable per input text but carry no real semantic meaning —
    suitable for exercising the retrieval *pipeline* in tests, not for
    asserting anything about which document is "most similar".
    """

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self.dim)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def get_embeddings(provider: str | None = None) -> Embeddings:
    """
    Factory function for the embeddings client used by Phase 1.D RAG retrieval.

    Deliberately separate from get_llm()'s chat-model provider list and not
    tied to AWS Bedrock Titan Embeddings -- see README.md's Phase 1.D ADR for
    why RAG is decoupled from a specific cloud provider. The Bedrock/Titan
    embeddings path is Phase 6 work, not implemented here.

    Args:
        provider: Override the default provider from settings. Supports
            'gemini' (AI Studio, API key), 'vertex' (Vertex AI, ADC; same
            embedding model family) and 'mock'.
    """
    if provider is None:
        provider = settings.LLM_PROVIDER
    provider = provider.lower().strip()

    if provider == "mock":
        return _DeterministicHashEmbeddings(dim=768)

    if provider == "vertex":
        if GoogleGenerativeAIEmbeddings is None:
            raise ImportError("langchain-google-genai is not installed")
        return cast(Embeddings, GoogleGenerativeAIEmbeddings(
            model=settings.VERTEX_EMBEDDING_MODEL,
            vertexai=True,
            project=settings.VERTEX_PROJECT or None,
            location=settings.VERTEX_LOCATION,
            output_dimensionality=768,
        ))

    if provider == "gemini":
        if GoogleGenerativeAIEmbeddings is None:
            raise ImportError("langchain-google-genai is not installed")
        return cast(Embeddings, GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            api_key=SecretStr(settings.GEMINI_API_KEY),
            output_dimensionality=768,
        ))

    raise ValueError(
        f"No embeddings provider configured for LLM_PROVIDER={provider!r}. "
        "Phase 1.D currently supports 'gemini'/'vertex' and 'mock'."
    )
