from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import SecretStr

from src.agents.llm_factory import get_llm
from src.core.config import Settings


def test_get_llm_mock():
    """Test that the factory returns a FakeListChatModel when LLM_PROVIDER=mock."""
    mock_settings = Settings(LLM_PROVIDER="mock")
    with patch("src.agents.llm_factory.settings", mock_settings):
        llm = get_llm()
        assert isinstance(llm, FakeListChatModel)
        assert llm.responses == ['{"verdict": "APPROVE", "reason": "Mocked for local dev"}']


def test_get_llm_mock_prompt_guard_returns_benign_score():
    """The Prompt Guard parses a bare float score, not the judges' JSON, so its
    mock must answer with a benign score or the guard would fail open as
    'skipped' on every claim."""
    from src.agents.llm_factory import PROMPT_GUARD_MODEL

    llm = get_llm(provider="mock", temperature=0.0, model_name=PROMPT_GUARD_MODEL)

    assert isinstance(llm, FakeListChatModel)
    assert llm.responses == ["0.0"]


def test_get_llm_gemini():
    """Test that the factory returns a Gemini model when LLM_PROVIDER=gemini."""
    mock_settings = Settings(LLM_PROVIDER="gemini", GEMINI_API_KEY="test_key")
    with patch("src.agents.llm_factory.settings", mock_settings), \
         patch("src.agents.llm_factory.ChatGoogleGenerativeAI") as MockGemini:
        mock_instance = MagicMock(spec=BaseChatModel)
        MockGemini.return_value = mock_instance
        
        llm = get_llm()
        
        assert llm is mock_instance
        MockGemini.assert_called_once_with(
            model="gemini-3.5-flash-lite",
            google_api_key="test_key",
            temperature=0.7
        )


def test_get_llm_openai():
    """Test that the factory returns an OpenAI model when LLM_PROVIDER=openai."""
    mock_settings = Settings(LLM_PROVIDER="openai", OPENAI_API_KEY="test_key")
    with patch("src.agents.llm_factory.settings", mock_settings), \
         patch("src.agents.llm_factory.ChatOpenAI") as MockOpenAI:
        mock_instance = MagicMock(spec=BaseChatModel)
        MockOpenAI.return_value = mock_instance
        
        llm = get_llm()
        
        assert llm is mock_instance
        MockOpenAI.assert_called_once()
        call_kwargs = MockOpenAI.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"
        assert isinstance(call_kwargs["api_key"], SecretStr)
        assert call_kwargs["api_key"].get_secret_value() == "test_key"
        assert call_kwargs["temperature"] == 0.7


def test_get_llm_groq():
    """Test that the factory returns a Groq model when LLM_PROVIDER=groq."""
    mock_settings = Settings(LLM_PROVIDER="groq", GROQ_API_KEY="test_key")
    with patch("src.agents.llm_factory.settings", mock_settings), \
         patch("src.agents.llm_factory.ChatGroq") as MockGroq:
        mock_instance = MagicMock(spec=BaseChatModel)
        MockGroq.return_value = mock_instance
        
        llm = get_llm()
        
        assert llm is mock_instance
        MockGroq.assert_called_once()
        call_kwargs = MockGroq.call_args.kwargs
        assert call_kwargs["model"] == "openai/gpt-oss-20b"
        assert isinstance(call_kwargs["api_key"], SecretStr)
        assert call_kwargs["api_key"].get_secret_value() == "test_key"
        assert call_kwargs["temperature"] == 0.7


def test_get_llm_vertex():
    """Test that the factory returns a Vertex model when LLM_PROVIDER=vertex."""
    mock_settings = Settings(LLM_PROVIDER="vertex")
    with patch("src.agents.llm_factory.settings", mock_settings), \
         patch("src.agents.llm_factory.ChatVertexAI") as MockVertex:
        mock_instance = MagicMock(spec=BaseChatModel)
        MockVertex.return_value = mock_instance
        
        llm = get_llm()
        
        assert llm is mock_instance
        MockVertex.assert_called_once_with(
            model_name="gemini-1.5-pro",
            temperature=0.7
        )


def test_get_llm_bedrock():
    """Test that the factory returns a Bedrock model when LLM_PROVIDER=bedrock."""
    mock_settings = Settings(LLM_PROVIDER="bedrock")
    with patch("src.agents.llm_factory.settings", mock_settings), \
         patch("src.agents.llm_factory.ChatBedrock") as MockBedrock:
        mock_instance = MagicMock(spec=BaseChatModel)
        MockBedrock.return_value = mock_instance
        
        llm = get_llm()
        
        assert llm is mock_instance
        MockBedrock.assert_called_once_with(
            model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
            region_name="us-east-1",
            model_kwargs={"temperature": 0.7}
        )


def test_get_llm_unknown_provider():
    """Test that the factory raises ValueError for an unknown provider."""
    mock_settings = Settings(LLM_PROVIDER="unknown")
    with patch("src.agents.llm_factory.settings", mock_settings), \
         pytest.raises(ValueError, match="Unsupported LLM_PROVIDER: unknown"):
            get_llm()


def test_get_embeddings_mock_returns_deterministic_768dim_vectors():
    """The 'mock' embeddings provider needs no API key and matches the
    knowledge_base table's vector(768) column."""
    from src.agents.llm_factory import get_embeddings

    embeddings = get_embeddings(provider="mock")

    vec_a = embeddings.embed_query("refund request")
    vec_b = embeddings.embed_query("refund request")
    vec_c = embeddings.embed_query("something else entirely")

    assert len(vec_a) == 768
    assert vec_a == vec_b  # deterministic for the same input
    assert vec_a != vec_c


def test_get_embeddings_gemini_uses_text_embedding_004():
    from src.agents.llm_factory import get_embeddings

    mock_settings = Settings(LLM_PROVIDER="gemini", GEMINI_API_KEY="test_key")
    with patch("src.agents.llm_factory.settings", mock_settings), \
         patch("src.agents.llm_factory.GoogleGenerativeAIEmbeddings") as MockEmbeddings:
        mock_instance = MagicMock()
        MockEmbeddings.return_value = mock_instance

        embeddings = get_embeddings()

        assert embeddings is mock_instance
        MockEmbeddings.assert_called_once()
        call_kwargs = MockEmbeddings.call_args.kwargs
        assert call_kwargs["model"] == "models/gemini-embedding-001"
        assert call_kwargs["api_key"].get_secret_value() == "test_key"
        assert call_kwargs["output_dimensionality"] == 768


def test_get_embeddings_unknown_provider_raises():
    from src.agents.llm_factory import get_embeddings

    mock_settings = Settings(LLM_PROVIDER="unknown")
    with patch("src.agents.llm_factory.settings", mock_settings), \
         pytest.raises(ValueError, match="No embeddings provider configured"):
            get_embeddings()
