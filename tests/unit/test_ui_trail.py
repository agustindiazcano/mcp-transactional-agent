from src.ui.trail import describe_prompt_guard


def test_describe_prompt_guard_returns_none_when_not_recorded():
    """Rows processed before the guard was tracked have no entry."""
    assert describe_prompt_guard(None) is None


def test_describe_prompt_guard_clear_shows_score():
    assert describe_prompt_guard({"status": "clear", "score": 0.0006, "reason": None}) == (
        "clear (score 0.001)"
    )


def test_describe_prompt_guard_blocked_shows_score():
    assert describe_prompt_guard({"status": "blocked", "score": 0.9989, "reason": None}) == (
        "BLOCKED (score 0.999)"
    )


def test_describe_prompt_guard_skipped_shows_reason():
    """A skipped scan must read as a warning, never as a clean result."""
    entry = {"status": "skipped", "score": None, "reason": "ImportError: no langchain-groq"}

    assert describe_prompt_guard(entry) == (
        "SKIPPED -- input was not scanned (failed open): ImportError: no langchain-groq"
    )
