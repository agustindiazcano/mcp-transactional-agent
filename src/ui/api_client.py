"""Thin async HTTP client to the gateway's own API -- the dashboard's ONLY
data source (CLAUDE.md Section 5d: the UI never touches Postgres or the MCP
server directly). Async per CLAUDE.md Section 6; Streamlit's script model is
synchronous, so app.py invokes these via a small run_async() helper."""
from datetime import datetime
from typing import Any, cast

import httpx

from src.ui.config import settings


async def get_transactions(*, limit: int = 50) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{settings.GATEWAY_URL}/api/v1/transactions", params={"limit": limit}
        )
        response.raise_for_status()

    rows = cast(list[dict[str, Any]], response.json())
    for row in rows:
        row["created_at"] = datetime.fromisoformat(row["created_at"])
        row["updated_at"] = datetime.fromisoformat(row["updated_at"])
    return rows


async def get_system_health() -> dict[str, bool]:
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(f"{settings.GATEWAY_URL}/api/v1/system-health")
        response.raise_for_status()
    return cast(dict[str, bool], response.json())


async def post_claim(
    *,
    user_id: str,
    claim_text: str,
    order_id: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Submit a claim. Refund details left blank (None or "") are omitted,
    not sent as null: without both order_id and amount an approved claim has
    nothing to execute and routes to PENDING_HUMAN_REVIEW."""
    body: dict[str, Any] = {"user_id": user_id, "claim_text": claim_text}
    refund_fields = {"order_id": order_id, "amount": amount, "currency": currency}
    body.update({key: value for key, value in refund_fields.items() if value not in (None, "")})

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(f"{settings.GATEWAY_URL}/api/v1/claims", json=body)
        response.raise_for_status()
    return cast(dict[str, Any], response.json())
