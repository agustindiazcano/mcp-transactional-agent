from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from src.agents.llm_factory import get_llm
from src.core.config import Settings


def test_get_llm_gemini():
    """Test that the factory returns a Gemini model when LLM_PROVIDER=gemini."""
    mock_settings = Settings(LLM_PROVIDER="gemini", GEMINI_API_KEY="test_key")
    with patch("src.agents.llm_factory.settings", mock_settings):
        # We also need to mock ChatGoogleGenerativeAI to avoid actual initialization errors
        # if the library does immediate validation, though usually it just takes the key.
        with patch("src.agents.llm_factory.ChatGoogleGenerativeAI") as MockGemini:
            mock_instance = MagicMock(spec=BaseChatModel)
            MockGemini.return_value = mock_instance
            
            llm = get_llm()
            
            assert llm is mock_instance
            MockGemini.assert_called_once()
            
def test_get_llm_groq():
    """Test that the factory returns a Groq model when LLM_PROVIDER=groq."""
    mock_settings = Settings(LLM_PROVIDER="groq", GROQ_API_KEY="test_key")
    with patch("src.agents.llm_factory.settings", mock_settings):
        with patch("src.agents.llm_factory.ChatGroq") as MockGroq:
            mock_instance = MagicMock(spec=BaseChatModel)
            MockGroq.return_value = mock_instance
            
            llm = get_llm()
            
            assert llm is mock_instance
            MockGroq.assert_called_once()

def test_get_llm_unknown_provider():
    """Test that the factory raises ValueError for an unknown provider."""
    mock_settings = Settings(LLM_PROVIDER="unknown")
    with patch("src.agents.llm_factory.settings", mock_settings):
        with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER: unknown"):
            get_llm()
