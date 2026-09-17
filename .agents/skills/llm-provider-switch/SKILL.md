---
name: llm-provider-switch
description: >-
  Use this skill when the user asks to switch the active LLM provider between
  Gemini, Groq, and AWS Bedrock, or when the user needs to add a new LLM
  provider to the factory. Ensures the factory pattern is preserved and no
  business logic is modified.
---

# LLM Provider Switch Runbook

The system uses a factory pattern to abstract LLM instantiation. Switching
providers must never touch business logic files (`services/`, `worker.py`,
`agents/`). Only `app/agents/llm_factory.py` and environment variables change.

## Step 1 - Switch the Active Provider

Edit the `.env` file (or set the environment variable in your deployment
configuration):

```
LLM_PROVIDER=gemini   # or: groq, bedrock
```

That is the only change needed to switch providers in a correctly implemented
factory. If switching requires more changes, the factory is not correctly
implemented - fix the factory first.

## Step 2 - Verify the Factory Interface

The factory must implement this interface exactly:

```python
# app/agents/llm_factory.py

from langchain_core.language_models import BaseChatModel
from app.config import Settings


def create_llm(settings: Settings) -> BaseChatModel:
    """
    Instantiate and return the configured LLM.

    The caller must not know which provider is active.

    Args:
        settings: Application settings loaded from environment variables.

    Returns:
        A LangChain BaseChatModel instance.

    Raises:
        ValueError: If LLM_PROVIDER is not a recognized value.
    """
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=settings.gemini_api_key,
        )

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model="llama-3.1-70b-versatile",
            api_key=settings.groq_api_key,
        )

    if provider == "bedrock":
        from langchain_aws import ChatBedrock
        return ChatBedrock(
            model_id="amazon.nova-pro-v1:0",
            region_name=settings.aws_region,
        )

    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Expected: gemini, groq, bedrock.")
```

## Step 3 - Add a New Provider

To add a new provider (e.g., OpenAI):

1. Add the required environment variables to `app/config.py` and `.env.example`.
2. Add the new branch to `create_llm()` in `llm_factory.py`.
3. Install the provider package: add it to `requirements.txt`.
4. Write a unit test in `tests/unit/test_llm_factory.py` that mocks the new
   provider and asserts `create_llm(settings)` returns a `BaseChatModel`.

## Step 4 - Validate the Switch

```bash
# Set the provider in your environment, then:
pytest tests/unit/test_llm_factory.py -v

# Run a smoke test against the running system
python -c "
from app.config import Settings
from app.agents.llm_factory import create_llm
llm = create_llm(Settings())
print(type(llm).__name__)
"
```

The output must be the class name of the expected provider's model (e.g.,
`ChatGoogleGenerativeAI`, `ChatGroq`, `ChatBedrock`).

## Step 5 - Update Documentation

Add the new provider to the Environment Variables table in `GEMINI.md` and
`CLAUDE.md`, and update the `LLM_PROVIDER` description with the new valid value.
