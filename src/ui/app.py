"""Phase 4 Ops Dashboard -- a read-only Streamlit app.

Consumes ONLY the gateway's HTTP API (src/ui/api_client.py). Never imports
SQLAlchemy models/sessions or calls the MCP server directly -- see CLAUDE.md
Section 5d's API-consumer constraint and README's Phase 4 section.
"""
import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

import httpx
import pandas as pd
import streamlit as st

from src.core.currency import Currency
from src.ui.api_client import get_system_health, get_transactions, post_claim
from src.ui.stats import compute_p95_latency, compute_throughput
from src.ui.theme import CSS, status_css_class
from src.ui.trail import describe_prompt_guard

T = TypeVar("T")

TRANSACTION_LIMIT = 100
HEALTH_CACHE_TTL_SECONDS = 5
TABLE_REFRESH_SECONDS = 2


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Bridge Streamlit's synchronous script model to this module's async
    I/O functions (CLAUDE.md Section 6: all I/O must be async)."""
    return asyncio.run(coro)


@st.cache_data(ttl=HEALTH_CACHE_TTL_SECONDS)
def load_system_health() -> dict[str, bool]:
    """Cached independently of the transaction table's own 2s refresh --
    health-check cadence and transaction-table cadence are different
    phenomena with different natural periods."""
    return run_async(get_system_health())


def render_health_strip() -> None:
    health = load_system_health()
    items = []
    for label, key in (("Gateway", "gateway"), ("PostgreSQL", "db"), ("MCP Server", "mcp")):
        up = health.get(key, False)
        css_class = "dashboard-health-item" if up else "dashboard-health-item down"
        status_text = "UP" if up else "DOWN"
        items.append(f'<span class="{css_class}">{label}: {status_text}</span>')
    st.markdown(f'<div class="dashboard-health-strip">{"".join(items)}</div>', unsafe_allow_html=True)


def render_ingestion_column() -> None:
    st.subheader("Submit Claim")
    user_id = st.text_input("User ID", value="user-1")
    claim_text = st.text_area("Claim Text", height=150)
    # Without order_id and amount an approved claim has nothing to execute
    # and routes to PENDING_HUMAN_REVIEW instead of COMPLETED.
    order_id = st.text_input("Order ID", value="").strip()
    amount = st.number_input("Refund Amount", min_value=0.01, value=None, step=1.0, format="%.2f")
    currency = st.selectbox("Currency", [c.value for c in Currency])
    if st.button("Submit"):
        if not claim_text.strip():
            st.warning("Claim text cannot be empty.")
            return
        try:
            result = run_async(
                post_claim(
                    user_id=user_id,
                    claim_text=claim_text,
                    order_id=order_id,
                    amount=amount,
                    currency=currency,
                )
            )
        except httpx.HTTPStatusError as exc:
            # e.g. a 422 for an amount above REFUND_MAX_AMOUNT.
            st.error(f"Gateway rejected the claim ({exc.response.status_code}): {exc.response.text}")
            return
        st.success(f"{result.get('status')} -- request_id: {result.get('request_id')}")


def render_judge_trail(judge_trail: dict[str, Any] | None) -> None:
    if not judge_trail:
        st.markdown(
            '<span class="dashboard-muted">Reasoning trail not recorded '
            "(transaction processed before this was tracked).</span>",
            unsafe_allow_html=True,
        )
        return

    guard_line = describe_prompt_guard(judge_trail.get("prompt_guard"))
    if guard_line:
        st.markdown(f"**Prompt Guard:** {guard_line}")

    for label, key in (("Judge 1 (Gemini)", "judge1"), ("Judge 2 (Groq)", "judge2")):
        entry = judge_trail.get(key)
        if entry:
            st.markdown(f"**{label}:** {entry.get('verdict')} -- {entry.get('reason')}")

    supreme_court = judge_trail.get("supreme_court")
    if supreme_court:
        st.markdown(f"**Supreme Court:** {supreme_court.get('verdict')} -- {supreme_court.get('reason')}")

    st.markdown(
        '<span class="dashboard-muted">Belief Rule Base (Phase 2): not yet implemented.</span>',
        unsafe_allow_html=True,
    )


@st.fragment(run_every=TABLE_REFRESH_SECONDS)
def render_transaction_monitor() -> None:
    rows = run_async(get_transactions(limit=TRANSACTION_LIMIT))

    throughput = compute_throughput(rows, window_seconds=60)
    p95 = compute_p95_latency(rows)
    stat_col1, stat_col2 = st.columns(2)
    stat_col1.metric("Throughput (last 60s)", throughput)
    stat_col2.metric("P95 Latency (s)", f"{p95:.2f}" if p95 is not None else "N/A")

    if not rows:
        st.markdown('<span class="dashboard-muted">No transactions yet.</span>', unsafe_allow_html=True)
        return

    table_rows = [
        {
            "request_id": row["request_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

    for row in rows:
        css_class = status_css_class(row["status"])
        label = f'{row["request_id"]} -- {row["status"]}'
        with st.expander(label):
            st.markdown(f'<span class="{css_class}">Status: {row["status"]}</span>', unsafe_allow_html=True)
            st.json(row["payload"])
            render_judge_trail(row.get("judge_trail"))


def main() -> None:
    st.set_page_config(page_title="Agentic MCP Engine -- Ops Dashboard", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    render_health_strip()

    left, right = st.columns([35, 65])
    with left:
        render_ingestion_column()
    with right:
        st.subheader("Transaction Monitor")
        render_transaction_monitor()


if __name__ == "__main__":
    main()
