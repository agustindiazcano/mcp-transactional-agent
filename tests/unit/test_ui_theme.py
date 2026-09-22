from src.ui.theme import status_css_class


def test_alert_class_for_pending_human_review() -> None:
    assert status_css_class("PENDING_HUMAN_REVIEW") == "dashboard-status-alert"


def test_alert_class_for_blocked_malicious_prompt() -> None:
    assert status_css_class("BLOCKED_MALICIOUS_PROMPT") == "dashboard-status-alert"


def test_ok_class_for_completed() -> None:
    assert status_css_class("COMPLETED") == "dashboard-status-ok"


def test_ok_class_for_processing() -> None:
    assert status_css_class("PROCESSING") == "dashboard-status-ok"
