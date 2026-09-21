"""Unit tests for strict concurrency control in worker.process_message.

Tests cover:
1. Race condition path: IntegrityError on INSERT -> ACK and discard (no LLM call).
2. Happy path:  INSERT succeeds -> judge APPROVE -> SELECT FOR UPDATE -> COMPLETED.
3. Rejection path: judge REJECT all retries -> SELECT FOR UPDATE -> PENDING_HUMAN_REVIEW.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError


def _make_message(body: dict) -> MagicMock:
    msg = MagicMock()
    msg.body = json.dumps(body).encode()
    msg.ack = AsyncMock()
    msg.nack = AsyncMock()
    return msg


def _make_db_session(*, flush_raises: bool = False) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()

    if flush_raises:
        session.flush = AsyncMock(
            side_effect=IntegrityError("INSERT", {}, Exception("duplicate key"))
        )
    else:
        session.flush = AsyncMock()

    locked_row = MagicMock()
    locked_row.status = "PROCESSING"
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one=MagicMock(return_value=locked_row))
    )
    return session


BODY = {
    "request_id": "req-test-001",
    "user_id": "usr-123",
    "claim_text": "I need a refund of 50 dollars.",
}


@pytest.mark.asyncio
async def test_race_condition_integrity_error_discards_message() -> None:
    message = _make_message(BODY)
    db_session = _make_db_session(flush_raises=True)

    with (
        patch("src.worker.worker.check_for_injection", new_callable=AsyncMock) as mock_guard,
        patch("src.worker.worker.evaluate_decision", new_callable=AsyncMock) as mock_judge,
        patch("src.worker.worker.get_llm"),
        patch("src.worker.worker.sse_client"),
    ):
        from src.worker.worker import process_message
        await process_message(message, db_session)

    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()
    mock_guard.assert_not_awaited()
    mock_judge.assert_not_awaited()
    db_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_happy_path_approve_uses_pessimistic_lock() -> None:
    message = _make_message(BODY)
    db_session = _make_db_session()

    approve_result = {"verdict": "APPROVE", "reason": "All checks passed."}

    mcp_session_mock = AsyncMock()
    mcp_session_mock.initialize = AsyncMock()

    with (
        patch("src.worker.worker.check_for_injection", new_callable=AsyncMock, return_value=False),
        patch("src.worker.worker.evaluate_decision", new_callable=AsyncMock, return_value=approve_result),
        patch("src.worker.worker.get_llm"),
        patch("src.worker.worker.get_embeddings") as mock_get_embeddings,
        patch("src.worker.worker.retrieve_relevant_policy", new_callable=AsyncMock, return_value=None),
        patch("src.worker.worker.sse_client") as mock_sse,
        patch("src.worker.worker.ClientSession") as mock_cs,
    ):
        mock_sse.return_value.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_sse.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_cs.return_value.__aenter__ = AsyncMock(return_value=mcp_session_mock)
        mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

        from src.worker.worker import process_message
        await process_message(message, db_session)

    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()
    db_session.execute.assert_awaited()
    locked_row = db_session.execute.return_value.scalar_one.return_value
    assert locked_row.status == "COMPLETED"
    mock_get_embeddings.assert_called_once()


@pytest.mark.asyncio
async def test_all_retries_exhausted_routes_to_human_review() -> None:
    message = _make_message(BODY)
    db_session = _make_db_session()
    reject_result = {"verdict": "REJECT", "reason": "Missing amount field."}

    mcp_session_mock = AsyncMock()
    mcp_session_mock.initialize = AsyncMock()

    with (
        patch("src.worker.worker.check_for_injection", new_callable=AsyncMock, return_value=False),
        patch("src.worker.worker.evaluate_decision", new_callable=AsyncMock, return_value=reject_result),
        patch("src.worker.worker.get_llm"),
        patch("src.worker.worker.get_embeddings"),
        patch("src.worker.worker.retrieve_relevant_policy", new_callable=AsyncMock, return_value=None),
        patch("src.worker.worker.sse_client") as mock_sse,
        patch("src.worker.worker.ClientSession") as mock_cs,
        patch("src.worker.worker.settings") as mock_settings,
    ):
        mock_settings.MCP_SERVER_URL = "http://localhost:8080"
        mock_settings.MAX_LLM_RETRIES = 2
        mock_sse.return_value.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_sse.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_cs.return_value.__aenter__ = AsyncMock(return_value=mcp_session_mock)
        mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

        from src.worker.worker import process_message
        await process_message(message, db_session)

    message.ack.assert_awaited_once()
    locked_row = db_session.execute.return_value.scalar_one.return_value
    assert locked_row.status == "PENDING_HUMAN_REVIEW"


@pytest.mark.asyncio
async def test_retrieved_policy_is_injected_into_judge_context() -> None:
    """Phase 1.D: a retrieved policy chunk must reach evaluate_decision's
    `context` argument, since that's the only real LLM call site available
    to carry it until the primary agent's own prompt-building loop exists."""
    message = _make_message(BODY)
    db_session = _make_db_session()
    approve_result = {"verdict": "APPROVE", "reason": "All checks passed."}

    mcp_session_mock = AsyncMock()
    mcp_session_mock.initialize = AsyncMock()

    with (
        patch("src.worker.worker.check_for_injection", new_callable=AsyncMock, return_value=False),
        patch("src.worker.worker.evaluate_decision", new_callable=AsyncMock, return_value=approve_result) as mock_judge,
        patch("src.worker.worker.get_llm"),
        patch("src.worker.worker.get_embeddings"),
        patch(
            "src.worker.worker.retrieve_relevant_policy",
            new_callable=AsyncMock,
            return_value="Refunds are issued within 30 days of purchase.",
        ) as mock_retrieve,
        patch("src.worker.worker.sse_client") as mock_sse,
        patch("src.worker.worker.ClientSession") as mock_cs,
    ):
        mock_sse.return_value.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_sse.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_cs.return_value.__aenter__ = AsyncMock(return_value=mcp_session_mock)
        mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

        from src.worker.worker import process_message
        await process_message(message, db_session)

    mock_retrieve.assert_awaited_once()
    assert mock_retrieve.await_args.args[2] == BODY["claim_text"]
    mock_judge.assert_awaited_once()
    judge_context = mock_judge.await_args.kwargs["context"]
    assert judge_context["retrieved_policy"] == "Refunds are issued within 30 days of purchase."


@pytest.mark.asyncio
async def test_retrieval_failure_fails_open_and_does_not_block_processing() -> None:
    """A retrieval/embeddings outage must never block transaction processing
    (same fail-open principle as prompt_guard.py's guard check)."""
    message = _make_message(BODY)
    db_session = _make_db_session()
    approve_result = {"verdict": "APPROVE", "reason": "All checks passed."}

    mcp_session_mock = AsyncMock()
    mcp_session_mock.initialize = AsyncMock()

    with (
        patch("src.worker.worker.check_for_injection", new_callable=AsyncMock, return_value=False),
        patch("src.worker.worker.evaluate_decision", new_callable=AsyncMock, return_value=approve_result) as mock_judge,
        patch("src.worker.worker.get_llm"),
        patch("src.worker.worker.get_embeddings", side_effect=RuntimeError("embeddings API down")),
        patch("src.worker.worker.sse_client") as mock_sse,
        patch("src.worker.worker.ClientSession") as mock_cs,
    ):
        mock_sse.return_value.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_sse.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_cs.return_value.__aenter__ = AsyncMock(return_value=mcp_session_mock)
        mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

        from src.worker.worker import process_message
        await process_message(message, db_session)

    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()
    judge_context = mock_judge.await_args.kwargs["context"]
    assert "retrieved_policy" not in judge_context
    locked_row = db_session.execute.return_value.scalar_one.return_value
    assert locked_row.status == "COMPLETED"
