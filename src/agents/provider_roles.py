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
    make no paid calls. Any other value keeps the fixed pairing above.
    """
    if settings.LLM_PROVIDER.lower().strip() == "mock":
        return "mock"
    return DEFAULT_ROLE_PROVIDERS[role]
