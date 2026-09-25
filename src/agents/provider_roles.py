"""Which LLM provider answers each pipeline role.

The first slice of Phase 1.F (dynamic provider selection): one place that maps
a role to a provider, instead of a provider literal at each call site. Phase
1.F's per-request and hot-swappable overrides are meant to extend this lookup.
"""

from typing import Literal

from src.core.config import settings

LlmRole = Literal["judge1", "judge2", "supreme_court", "prompt_guard"]

# The asymmetric Double Judge needs two different model families, and the
# Prompt Guard is a Groq-hosted classifier, so these don't follow LLM_PROVIDER.
DEFAULT_ROLE_PROVIDERS: dict[LlmRole, str] = {
    "judge1": "gemini",
    "judge2": "groq",
    "supreme_court": "gemini",
    "prompt_guard": "groq",
}


def provider_for_role(role: LlmRole) -> str:
    """Return the provider that answers ``role``.

    LLM_PROVIDER=mock routes every role to the mock, so local and load-test runs
    make no paid calls. LLM_PROVIDER=vertex runs the Gemini roles on Vertex AI
    (same model family, service-account auth on GCP). Any other value keeps the
    fixed pairing above.
    """
    configured = settings.LLM_PROVIDER.lower().strip()
    if configured == "mock":
        return "mock"
    provider = DEFAULT_ROLE_PROVIDERS[role]
    if configured == "vertex" and provider == "gemini":
        return "vertex"
    return provider


def model_for_role(role: LlmRole) -> str | None:
    """Return the model ``role`` runs on, or None for its provider's default.

    Only the Supreme Court has its own model: on Judge 1's model it would repeat
    Judge 1's verdict on the very disagreements it exists to break (measured in
    docs/testing/judge_evaluation_results.md). The mock takes no model name.
    """
    if role == "supreme_court" and provider_for_role(role) in ("gemini", "vertex"):
        return settings.SUPREME_COURT_MODEL
    return None
