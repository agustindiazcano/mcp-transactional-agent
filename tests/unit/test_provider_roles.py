import pytest

from src.agents.provider_roles import DEFAULT_ROLE_PROVIDERS, LlmRole, provider_for_role
from src.core.config import settings

ALL_ROLES: list[LlmRole] = ["judge1", "judge2", "supreme_court", "prompt_guard"]


@pytest.mark.parametrize("role", ALL_ROLES)
def test_mock_mode_routes_every_role_to_mock(
    monkeypatch: pytest.MonkeyPatch, role: LlmRole
) -> None:
    """LLM_PROVIDER=mock must reach every role, so a load/chaos run makes no
    paid calls and hits no provider rate limit."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")

    assert provider_for_role(role) == "mock"


def test_mock_mode_is_case_and_whitespace_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", " MOCK ")

    assert provider_for_role("judge2") == "mock"


@pytest.mark.parametrize("configured", ["gemini", "groq", "openai", "bedrock"])
def test_real_provider_keeps_the_fixed_role_pairing(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    """Outside mock mode nothing changes: the asymmetric Double Judge keeps two
    model families and the guard stays on Groq, whatever LLM_PROVIDER says."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", configured)

    assert provider_for_role("judge1") == "gemini"
    assert provider_for_role("judge2") == "groq"
    assert provider_for_role("supreme_court") == "gemini"
    assert provider_for_role("prompt_guard") == "groq"


def test_vertex_mode_moves_the_gemini_roles_to_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    """On GCP the Gemini roles run on Vertex AI (same model family, service-account
    auth). Judge 2 and the guard stay on Groq, so the Double Judge keeps two
    model families."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "vertex")

    assert provider_for_role("judge1") == "vertex"
    assert provider_for_role("supreme_court") == "vertex"
    assert provider_for_role("judge2") == "groq"
    assert provider_for_role("prompt_guard") == "groq"


def test_default_pairing_covers_every_role() -> None:
    assert set(DEFAULT_ROLE_PROVIDERS) == set(ALL_ROLES)


@pytest.mark.parametrize("configured", ["gemini", "vertex"])
def test_supreme_court_runs_its_own_model(monkeypatch: pytest.MonkeyPatch, configured: str) -> None:
    """The judge benchmark (docs/testing/judge_evaluation_results.md) showed that a
    Supreme Court on Judge 1's model repeats Judge 1's verdict on a disagreement,
    so it gets its own model (SUPREME_COURT_MODEL, default gemini-3.8-flash)."""
    from src.agents.provider_roles import model_for_role

    monkeypatch.setattr(settings, "LLM_PROVIDER", configured)
    monkeypatch.setattr(settings, "SUPREME_COURT_MODEL", "gemini-test-court")

    assert model_for_role("supreme_court") == "gemini-test-court"


@pytest.mark.parametrize("role", ["judge1", "judge2", "prompt_guard"])
def test_other_roles_keep_their_providers_default_model(role: LlmRole) -> None:
    from src.agents.provider_roles import model_for_role

    assert model_for_role(role) is None


def test_mock_mode_gives_the_supreme_court_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mock ignores model names except the Prompt Guard's; pass none."""
    from src.agents.provider_roles import model_for_role

    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")

    assert model_for_role("supreme_court") is None


def test_supreme_court_default_is_the_benchmarked_model() -> None:
    from src.core.config import Settings

    assert Settings().SUPREME_COURT_MODEL == "gemini-3.8-flash"
