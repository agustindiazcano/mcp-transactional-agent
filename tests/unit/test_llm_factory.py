from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from src.agents.llm_factory import get_llm
from src.core.config import Settings


def test_get_llm_mock():
    """Test that the factory returns a FakeListChatModel when LLM_PROVIDER=mock."""
    mock_settings = Settings(LLM_PROVIDER="mock")
    with patch("src.agents.llm_factory.settings", mock_settings):
        llm = get_llm()
        assert isinstance(llm, FakeListChatModel)
        assert llm.responses == ['{"verdict": "APPROVE", "reason": "Mocked for local dev"}']


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
            model="gemini-1.5-flash",
            google_api_key="test_key"
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
        MockOpenAI.assert_called_once_with(
            model="gpt-4o",
            api_key="test_key"
        )


def test_get_llm_groq():
    """Test that the factory returns a Groq model when LLM_PROVIDER=groq."""
    mock_settings = Settings(LLM_PROVIDER="groq", GROQ_API_KEY="test_key")
    with patch("src.agents.llm_factory.settings", mock_settings), \
         patch("src.agents.llm_factory.ChatGroq") as MockGroq:
        mock_instance = MagicMock(spec=BaseChatModel)
        MockGroq.return_value = mock_instance
        
        llm = get_llm()
        
        assert llm is mock_instance
        MockGroq.assert_called_once_with(
            model="llama3-70b-8192",
            api_key="test_key"
        )


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
            model_name="gemini-1.5-pro"
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
            region_name="us-east-1"
        )


def test_get_llm_unknown_provider():
    """Test that the factory raises ValueError for an unknown provider."""
    mock_settings = Settings(LLM_PROVIDER="unknown")
    with patch("src.agents.llm_factory.settings", mock_settings), \
         pytest.raises(ValueError, match="Unsupported LLM_PROVIDER: unknown"):
            get_llm()
