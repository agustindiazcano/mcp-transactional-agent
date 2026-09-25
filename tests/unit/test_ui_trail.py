from src.ui.trail import describe_clarification_question, describe_prompt_guard


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


def test_describe_clarification_question_returns_none_when_not_recorded():
    assert describe_clarification_question(None) is None


def test_describe_clarification_question_returns_none_for_a_refund_proposal():
    trail = {"front_desk": {"intent": "refund", "reason": "Wants $50 back."}}
    assert describe_clarification_question(trail) is None


def test_describe_clarification_question_returns_none_for_out_of_scope():
    trail = {"front_desk": {"intent": "out_of_scope", "reason": "Not a refund request."}}
    assert describe_clarification_question(trail) is None


def test_describe_clarification_question_reads_the_initial_proposal():
    trail = {"front_desk": {"intent": "clarify", "reason": "What order and amount?"}}
    assert describe_clarification_question(trail) == "What order and amount?"


def test_describe_clarification_question_prefers_the_retry_reclassification():
    """A judge REJECT can trigger one reclassification attempt; if that one
    asks a different question, it supersedes the initial proposal's."""
    trail = {
        "front_desk": {"intent": "refund", "reason": "Wants $50 back."},
        "front_desk_retry": {"intent": "clarify", "reason": "Which order is this about?"},
    }
    assert describe_clarification_question(trail) == "Which order is this about?"
