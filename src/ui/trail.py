"""Pure formatting of a transaction's judge_trail entries for the dashboard.
No I/O and no Streamlit import -- unit-testable in isolation, like stats.py."""
from typing import Any


def describe_prompt_guard(entry: dict[str, Any] | None) -> str | None:
    """One-line summary of the trail's 'prompt_guard' entry, or None if absent.

    A 'skipped' scan is spelled out as unscanned so a failed-open guard is
    never mistaken for a clean result.
    """
    if not entry:
        return None
    status = entry.get("status")
    if status == "skipped":
        return f"SKIPPED -- input was not scanned (failed open): {entry.get('reason')}"
    label = "BLOCKED" if status == "blocked" else str(status)
    return f"{label} (score {entry.get('score', 0.0):.3f})"


def describe_clarification_question(judge_trail: dict[str, Any] | None) -> str | None:
    """The Front-Desk's clarifying question, or None if it never proposed
    'clarify'.

    The one reclassification attempt on a judge REJECT (`front_desk_retry`)
    supersedes the initial proposal (`front_desk`) when both are present --
    it is the more recent read of what's missing.
    """
    if not judge_trail:
        return None
    entry = judge_trail.get("front_desk_retry") or judge_trail.get("front_desk")
    if entry and entry.get("intent") == "clarify":
        reason = entry.get("reason")
        return str(reason) if reason is not None else None
    return None
