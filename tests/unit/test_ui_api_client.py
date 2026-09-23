from unittest.mock import patch

import httpx
import pytest

from src.ui.api_client import get_system_health, get_transactions, post_claim


@pytest.mark.asyncio
async def test_get_transactions_parses_rows() -> None:
    payload = [
        {
            "request_id": "abc-1",
            "status": "COMPLETED",
            "created_at": "2026-09-22T00:00:00Z",
            "updated_at": "2026-09-22T00:00:05Z",
            "payload": {"user_id": "u1", "claim_text": "Refund $10"},
            "judge_trail": {
                "judge1": {"verdict": "APPROVE", "reason": "ok"},
                "judge2": {"verdict": "APPROVE", "reason": "ok"},
                "supreme_court": None,
            },
        }
    ]
    mock_response = httpx.Response(
        200, json=payload, request=httpx.Request("GET", "http://gateway/api/v1/transactions")
    )

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        rows = await get_transactions(limit=10)

    assert len(rows) == 1
    assert rows[0]["request_id"] == "abc-1"
    assert rows[0]["judge_trail"]["judge1"]["verdict"] == "APPROVE"
    # created_at/updated_at must be real datetimes, not raw strings, so
    # src/ui/stats.py can subtract them directly.
    assert rows[0]["created_at"].year == 2026


@pytest.mark.asyncio
async def test_get_system_health_returns_dict() -> None:
    mock_response = httpx.Response(
        200,
        json={"gateway": True, "db": True, "mcp": False},
        request=httpx.Request("GET", "http://gateway/api/v1/system-health"),
    )

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        health = await get_system_health()

    assert health == {"gateway": True, "db": True, "mcp": False}


@pytest.mark.asyncio
async def test_post_claim_returns_response_body() -> None:
    mock_response = httpx.Response(
        202,
        json={"status": "Accepted", "request_id": "new-req-1"},
        request=httpx.Request("POST", "http://gateway/api/v1/claims"),
    )

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        result = await post_claim(user_id="u1", claim_text="Refund $50")

    assert result == {"status": "Accepted", "request_id": "new-req-1"}


@pytest.mark.asyncio
async def test_post_claim_sends_refund_details_when_given() -> None:
    mock_response = httpx.Response(
        202,
        json={"status": "Accepted", "request_id": "new-req-2"},
        request=httpx.Request("POST", "http://gateway/api/v1/claims"),
    )

    with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
        await post_claim(
            user_id="u1",
            claim_text="Refund $50",
            order_id="ord-1",
            amount=50.0,
            currency="USD",
        )

    assert mock_post.call_args.kwargs["json"] == {
        "user_id": "u1",
        "claim_text": "Refund $50",
        "order_id": "ord-1",
        "amount": 50.0,
        "currency": "USD",
    }


@pytest.mark.asyncio
async def test_post_claim_omits_refund_details_left_blank() -> None:
    """A blank field must be left out, not sent as null or "": the gateway's
    ClaimRequest rejects an empty order_id with a 422."""
    mock_response = httpx.Response(
        202,
        json={"status": "Accepted", "request_id": "new-req-3"},
        request=httpx.Request("POST", "http://gateway/api/v1/claims"),
    )

    with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
        await post_claim(user_id="u1", claim_text="Refund $50", order_id="", amount=None)

    assert mock_post.call_args.kwargs["json"] == {"user_id": "u1", "claim_text": "Refund $50"}
