---
name: llm-provider-switch
description: >-
  Use this skill when the user asks to switch the active LLM provider, or
  needs to add a new provider to the factory. Ensures the factory pattern in
  src/agents/llm_factory.py is preserved and no business logic is touched.
---

# LLM Provider Switch Runbook

The system uses a factory pattern (GEMINI.md's Interface Segregation and
Factory Pattern directive) to abstract LLM instantiation. Switching providers
must never touch business logic files (`src/core/services/`,
`src/worker/worker.py`, `src/agents/judge.py`). Only
`src/agents/llm_factory.py` and environment variables change.

## Step 1 - Switch the Active Provider

Set `LLM_PROVIDER` in `.env` (or the deployment environment):

```
LLM_PROVIDER=gemini   # or: mock, openai, vertex, bedrock, groq
```

`mock` returns a fixed valid judge JSON response via `FakeListChatModel` — use
it for local development without spending tokens. If switching requires more
than this one variable, the factory isn't correctly implemented — fix the
factory first, don't special-case the caller.

## Step 2 - Verify the Factory Interface

The actual interface, `get_llm()` in `src/agents/llm_factory.py` — not
`create_llm(settings)`, and config fields are the uppercase
`pydantic-settings` style (`settings.LLM_PROVIDER`, not `settings.llm_provider`):

```python
def get_llm(
    provider: str | None = None,
    temperature: float = 0.7,
    model_name: str | None = None,
) -> BaseChatModel:
    """
    Instantiate and return the configured LLM.

    provider defaults to settings.LLM_PROVIDER when not given, so most
    callers don't pass it explicitly — different components (primary agent
    vs. judge) can still override provider/temperature/model_name per call.
    """
```

Each provider's import is wrapped in `try/except ImportError` so an
uninstalled provider package doesn't break the whole module — only using
that provider does (`raise ImportError(...)` at call time).

**Vertex AI (primary cloud provider, Phase 6 — see GEMINI.md Section 5f):**
the `vertex` branch exists but is not deployable yet — `langchain-google-vertexai`
is not declared in `pyproject.toml` (a local `.venv` may have it installed, a
Docker image won't), and it hardcodes `model_name="gemini-1.5-pro"`. It
authenticates via ADC (`GOOGLE_APPLICATION_CREDENTIALS` locally, the Cloud Run
service account in GCP), never an API key. Note also that `get_llm()`'s
`provider` only switches callers that don't hardcode one: `judge.py` pins
Judge 1/Supreme Court to `"gemini"` and Judge 2 to `"groq"`, and
`prompt_guard.py` pins `"groq"` — per-judge selection is Phase 1.F, not done.

## Step 3 - Add a New Provider

1. Add the required environment variables to `src/core/config.py` (`Settings` class, uppercase field) and `.env.example`.
2. Add a new `elif provider == "<name>":` branch in `get_llm()`, following the existing `try/except ImportError` pattern.
3. Add the provider package to `pyproject.toml`'s `dependencies` (not `requirements.txt` — this project uses `pyproject.toml`/hatchling).
4. Write a unit test in `tests/unit/` that mocks the new provider and asserts `get_llm(provider="<name>")` returns a `BaseChatModel`.

## Step 4 - Validate the Switch

```bash
pytest tests/unit/ -k llm_factory -v

python -c "
from src.agents.llm_factory import get_llm
llm = get_llm()
print(type(llm).__name__)
"
```

The output should be the expected provider's model class name (e.g.
`ChatGoogleGenerativeAI`, `ChatVertexAI`, `ChatGroq`, `ChatBedrock`, `FakeListChatModel` for mock).

## Step 5 - Update Documentation

Add the new provider to the Environment Variables tables in **both**
README.md and Section 9 of CLAUDE.md / AGENTS.md / GEMINI.md (the three are kept identical) — they must stay in sync (see the doc
reconciliation work already done in this repo's history).
