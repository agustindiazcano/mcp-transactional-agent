"""Single source of the dashboard's visual theme -- kept fully separate from
data/logic (src/ui/app.py, api_client.py, stats.py) so it can be re-themed
without touching any of those. "Corporate deep-space terminal" look: near-
black background, one phosphor accent for normal state, red reserved
strictly for alert states.

Real Transaction.status values (worker.py): PROCESSING, COMPLETED,
PENDING_HUMAN_REVIEW, BLOCKED_MALICIOUS_PROMPT. There is no PENDING or
REJECTED status -- a judge reject routes to PENDING_HUMAN_REVIEW, not a
separate terminal state.
"""

BACKGROUND = "#05080a"
PANEL_BACKGROUND = "#0a1210"
PHOSPHOR = "#33ff99"
PHOSPHOR_DIM = "#1f8f5c"
ALERT_RED = "#ff3b3b"
TEXT_MUTED = "#5c7a70"

ALERT_STATUSES = {"PENDING_HUMAN_REVIEW", "BLOCKED_MALICIOUS_PROMPT"}

CSS = f"""
<style>
    .stApp {{
        background-color: {BACKGROUND};
        color: {PHOSPHOR};
        font-family: "Courier New", monospace;
    }}
    section[data-testid="stSidebar"], div[data-testid="stVerticalBlock"] > div {{
        border-color: {PHOSPHOR_DIM};
    }}
    .dashboard-health-strip {{
        display: flex;
        gap: 1.5rem;
        padding: 0.5rem 1rem;
        border: 1px solid {PHOSPHOR_DIM};
        background-color: {PANEL_BACKGROUND};
        border-radius: 4px;
        margin-bottom: 1rem;
    }}
    .dashboard-health-item {{
        color: {PHOSPHOR};
    }}
    .dashboard-health-item.down {{
        color: {ALERT_RED};
        font-weight: bold;
    }}
    .dashboard-status-alert {{
        color: {ALERT_RED};
        font-weight: bold;
    }}
    .dashboard-status-ok {{
        color: {PHOSPHOR};
    }}
    .dashboard-muted {{
        color: {TEXT_MUTED};
    }}
    div[data-testid="stExpander"] {{
        border: 1px solid {PHOSPHOR_DIM};
        background-color: {PANEL_BACKGROUND};
    }}
</style>
"""


def status_css_class(status: str) -> str:
    """CSS class for a transaction row's status -- red only for alert states."""
    return "dashboard-status-alert" if status in ALERT_STATUSES else "dashboard-status-ok"
