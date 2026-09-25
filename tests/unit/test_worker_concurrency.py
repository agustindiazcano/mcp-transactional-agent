"""Unit tests for strict concurrency control in worker.process_message.

Tests cover:
1. Race condition path: IntegrityError on INSERT -> ACK and discard (no LLM call).
2. Happy path:  INSERT succeeds -> judge APPROVE -> execute_refund via MCP ->
   SELECT FOR UPDATE -> COMPLETED.
3. Rejection path: judge REJECT all retries -> SELECT FOR UPDATE -> PENDING_HUMAN_REVIEW.
4. Execution paths: approved but not executable (no order_id/amount) ->
   PENDING_HUMAN_REVIEW; execution failure after retries -> EXECUTION_FAILED
   + nack(requeue=False).
"""
import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from src.agents.prompt_guard import GuardResult
from src.core.services.evidence_check import EvidenceCheck
from src.worker.evidence import EvidenceUnavailableError
from src.worker.refund_executor import RefundExecutionError

CLEAR_GUARD = GuardResult(status="clear", score=0.001)
APPROVE = {"verdict": "APPROVE", "reason": "All checks passed."}
EXECUTED = {
    "status": "executed",
    "refund_id": 7,
    "request_id": "req-test-001",
    "transaction_id": "ord-001",
    "amount": 50.0,
    "currency": "USD",
}

ORDER = {
    "order_id": "ord-001",
    "user_id": "usr-123",
    "amount": 80.0,
    "currency": "USD",
    "created_at": "2026-09-12T10:00:00+00:00",
}
PASSED_EVIDENCE = EvidenceCheck(
    order_id="ord-001",
    failures=(),
    order=ORDER,
    already_refunded=Decimal("0.00"),
    amount_usd=Decimal("50.00"),
)
FAILED_EVIDENCE = EvidenceCheck(
    order_id="ord-001",
    failures=("Refund 3000.00 USD exceeds what remains refundable on order ord-001 (80.00 USD).",),
    order=ORDER,
    already_refunded=Decimal("0.00"),
    amount_usd=Decimal("3000.00"),
)


def _make_message(body: dict[str, Any]) -> MagicMock:
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


def _locked_row(db_session: AsyncMock) -> MagicMock:
    row: MagicMock = db_session.execute.return_value.scalar_one.return_value
    return row


BODY: dict[str, Any] = {
    "request_id": "req-test-001",
    "user_id": "usr-123",
    "claim_text": "I need a refund of 50 dollars.",
    "order_id": "ord-001",
    "amount": 50.0,
    "currency": "USD",
}

BODY_WITHOUT_REFUND_DETAILS: dict[str, Any] = {
    "request_id": "req-test-002",
    "user_id": "usr-123",
    "claim_text": "My order arrived broken.",
    "order_id": None,
    "amount": None,
    "currency": None,
}


@contextmanager
def _pipeline(
    *,
    guard: GuardResult = CLEAR_GUARD,
    judge: dict[str, Any] | None = None,
    retrieved_policy: str | None = None,
    executor_result: dict[str, Any] | None = None,
    executor_error: Exception | None = None,
    evidence: EvidenceCheck = PASSED_EVIDENCE,
    evidence_error: Exception | None = None,
) -> Iterator[dict[str, MagicMock]]:
    """Patch every external dependency of process_message."""
    with ExitStack() as stack:
        mocks = {
            "guard": stack.enter_context(
                patch(
                    "src.worker.worker.scan_for_injection",
                    new_callable=AsyncMock,
                    return_value=guard,
                )
            ),
            "judge": stack.enter_context(
                patch(
                    "src.worker.worker.evaluate_decision",
                    new_callable=AsyncMock,
                    return_value=judge or APPROVE,
                )
            ),
            "get_llm": stack.enter_context(patch("src.worker.worker.get_llm")),
            "get_embeddings": stack.enter_context(patch("src.worker.worker.get_embeddings")),
            "retrieve": stack.enter_context(
                patch(
                    "src.worker.worker.retrieve_relevant_policy",
                    new_callable=AsyncMock,
                    return_value=retrieved_policy,
                )
            ),
            "executor": stack.enter_context(
                patch(
                    "src.worker.worker.execute_refund_via_mcp",
                    new_callable=AsyncMock,
                    return_value=executor_result or EXECUTED,
                    side_effect=executor_error,
                )
            ),
            "evidence": stack.enter_context(
                patch(
                    "src.worker.worker.verify_claim_evidence",
                    new_callable=AsyncMock,
                    return_value=evidence,
                    side_effect=evidence_error,
                )
            ),
        }
        yield mocks


@pytest.mark.asyncio
async def test_race_condition_integrity_error_discards_message() -> None:
    message = _make_message(BODY)
    db_session = _make_db_session(flush_raises=True)

    with _pipeline() as mocks:
        from src.worker.worker import process_message
        await process_message(message, db_session)

    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()
    mocks["guard"].assert_not_awaited()
    mocks["judge"].assert_not_awaited()
    mocks["executor"].assert_not_awaited()
    db_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_happy_path_approve_executes_refund_and_completes() -> None:
    message = _make_message(BODY)
    db_session = _make_db_session()

    with _pipeline() as mocks:
        from src.worker.worker import process_message
        await process_message(message, db_session)

    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()
    db_session.execute.assert_awaited()
    mocks["get_embeddings"].assert_called_once()

    call = mocks["executor"].await_args
    assert call.kwargs["request_id"] == "req-test-001"
    assert call.kwargs["transaction_id"] == "ord-001"
    assert call.kwargs["amount"] == 50.0
    assert call.kwargs["currency"] == "USD"

    locked_row = _locked_row(db_session)
    assert locked_row.status == "COMPLETED"
    assert locked_row.judge_trail["execution"] == EXECUTED


@pytest.mark.asyncio
async def test_currency_defaults_to_usd_when_claim_omits_it() -> None:
    message = _make_message({**BODY, "currency": None})
    db_session = _make_db_session()

    with _pipeline() as mocks:
        from src.worker.worker import process_message
        await process_message(message, db_session)

    assert mocks["executor"].await_args.kwargs["currency"] == "USD"


@pytest.mark.asyncio
async def test_execution_failure_marks_execution_failed_and_dead_letters() -> None:
    """Approved, but the refund could not be executed after every retry:
    the row records EXECUTION_FAILED and the message is NACKed without
    requeue, so it is neither lost silently nor retried forever."""
    message = _make_message(BODY)
    db_session = _make_db_session()

    with _pipeline(executor_error=RefundExecutionError("mcp unreachable")):
        from src.worker.worker import process_message
        await process_message(message, db_session)

    locked_row = _locked_row(db_session)
    assert locked_row.status == "EXECUTION_FAILED"
    assert locked_row.judge_trail["execution"] == {
        "status": "failed",
        "error": "mcp unreachable",
    }
    db_session.commit.assert_awaited()
    message.nack.assert_awaited_once_with(requeue=False)
    message.ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_approved_claim_without_refund_details_goes_to_human_review() -> None:
    """Nothing to execute without an order and an amount: an approval alone
    must not be reported as COMPLETED."""
    message = _make_message(BODY_WITHOUT_REFUND_DETAILS)
    db_session = _make_db_session()

    with _pipeline() as mocks:
        from src.worker.worker import process_message
        await process_message(message, db_session)

    mocks["executor"].assert_not_awaited()
    locked_row = _locked_row(db_session)
    assert locked_row.status == "PENDING_HUMAN_REVIEW"
    assert locked_row.judge_trail["execution"]["status"] == "not_executable"
    message.ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_retries_exhausted_routes_to_human_review() -> None:
    message = _make_message(BODY)
    db_session = _make_db_session()
    reject_result = {"verdict": "REJECT", "reason": "Missing amount field."}

    with (
        _pipeline(judge=reject_result) as mocks,
        patch("src.worker.worker.settings") as mock_settings,
    ):
        mock_settings.MAX_LLM_RETRIES = 2
        from src.worker.worker import process_message
        await process_message(message, db_session)

    message.ack.assert_awaited_once()
    assert mocks["judge"].await_count == 2
    mocks["executor"].assert_not_awaited()
    assert _locked_row(db_session).status == "PENDING_HUMAN_REVIEW"


@pytest.mark.asyncio
async def test_retrieved_policy_is_injected_into_judge_context() -> None:
    """Phase 1.D: a retrieved policy chunk must reach evaluate_decision's
    `context` argument, since that's the only real LLM call site available
    to carry it until the primary agent's own prompt-building loop exists."""
    message = _make_message(BODY)
    db_session = _make_db_session()

    with _pipeline(retrieved_policy="Refunds are issued within 30 days of purchase.") as mocks:
        from src.worker.worker import process_message
        await process_message(message, db_session)

    mocks["retrieve"].assert_awaited_once()
    assert mocks["retrieve"].await_args.args[2] == BODY["claim_text"]
    mocks["judge"].assert_awaited_once()
    judge_context = mocks["judge"].await_args.kwargs["context"]
    assert judge_context["retrieved_policy"] == "Refunds are issued within 30 days of purchase."


@pytest.mark.asyncio
async def test_retrieval_failure_fails_open_and_does_not_block_processing() -> None:
    """A retrieval/embeddings outage must never block transaction processing
    (same fail-open principle as prompt_guard.py's guard check)."""
    message = _make_message(BODY)
    db_session = _make_db_session()

    with _pipeline() as mocks:
        mocks["get_embeddings"].side_effect = RuntimeError("embeddings API down")
        from src.worker.worker import process_message
        await process_message(message, db_session)

    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()
    judge_context = mocks["judge"].await_args.kwargs["context"]
    assert "retrieved_policy" not in judge_context
    assert _locked_row(db_session).status == "COMPLETED"


@pytest.mark.asyncio
async def test_blocked_prompt_records_guard_result_in_trail() -> None:
    message = _make_message(BODY)
    db_session = _make_db_session()
    blocked = GuardResult(status="blocked", score=0.999)

    with _pipeline(guard=blocked) as mocks:
        from src.worker.worker import process_message
        await process_message(message, db_session)

    locked_row = _locked_row(db_session)
    assert locked_row.status == "BLOCKED_MALICIOUS_PROMPT"
    assert locked_row.judge_trail == {
        "prompt_guard": {"status": "blocked", "score": 0.999, "reason": None}
    }
    mocks["judge"].assert_not_awaited()
    mocks["executor"].assert_not_awaited()


@pytest.mark.asyncio
async def test_skipped_guard_is_recorded_alongside_judge_trail() -> None:
    """A guard that could not score the input fails open, but the
    transaction's trail must say so instead of looking like a clean scan."""
    message = _make_message(BODY)
    db_session = _make_db_session()
    skipped = GuardResult(status="skipped", reason="ImportError: langchain-groq is not installed")
    judge_trail = {
        "judge1": {"verdict": "APPROVE", "reason": "ok"},
        "judge2": {"verdict": "APPROVE", "reason": "ok"},
        "supreme_court": None,
    }
    approve = {"verdict": "APPROVE", "reason": "ok", "trail": judge_trail}

    with _pipeline(guard=skipped, judge=approve):
        from src.worker.worker import process_message
        await process_message(message, db_session)

    locked_row = _locked_row(db_session)
    assert locked_row.status == "COMPLETED"
    assert locked_row.judge_trail == {
        **judge_trail,
        "prompt_guard": {
            "status": "skipped",
            "score": None,
            "reason": "ImportError: langchain-groq is not installed",
        },
        "evidence": PASSED_EVIDENCE.to_trail(),
        "execution": EXECUTED,
    }


# ── Evidence for the judges (Part B) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_verified_evidence_reaches_the_judges_and_the_trail() -> None:
    message = _make_message(BODY)
    db_session = _make_db_session()

    with _pipeline() as mocks:
        from src.worker.worker import process_message
        await process_message(message, db_session)

    assert mocks["evidence"].await_args.args[0] == BODY
    judge_context = mocks["judge"].await_args.kwargs["context"]
    assert judge_context["evidence"] == PASSED_EVIDENCE.summary_for_judges()
    locked_row = _locked_row(db_session)
    assert locked_row.status == "COMPLETED"
    assert locked_row.judge_trail["evidence"] == PASSED_EVIDENCE.to_trail()


@pytest.mark.asyncio
async def test_failed_evidence_goes_to_human_review_without_judges() -> None:
    """The benchmark's $3,000 refund on a $30 order: code stops it, so no
    judge can approve it, and no LLM call is spent on it."""
    message = _make_message(BODY)
    db_session = _make_db_session()

    with _pipeline(evidence=FAILED_EVIDENCE) as mocks:
        from src.worker.worker import process_message
        await process_message(message, db_session)

    mocks["judge"].assert_not_awaited()
    mocks["executor"].assert_not_awaited()
    locked_row = _locked_row(db_session)
    assert locked_row.status == "PENDING_HUMAN_REVIEW"
    assert locked_row.judge_trail["evidence"] == FAILED_EVIDENCE.to_trail()
    assert locked_row.judge_trail["prompt_guard"]["status"] == "clear"
    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_evidence_fails_closed_to_human_review() -> None:
    message = _make_message(BODY)
    db_session = _make_db_session()

    with _pipeline(evidence_error=EvidenceUnavailableError("ConnectionError: refused")) as mocks:
        from src.worker.worker import process_message
        await process_message(message, db_session)

    mocks["judge"].assert_not_awaited()
    mocks["executor"].assert_not_awaited()
    locked_row = _locked_row(db_session)
    assert locked_row.status == "PENDING_HUMAN_REVIEW"
    assert locked_row.judge_trail["evidence"] == {
        "status": "unavailable",
        "error": "ConnectionError: refused",
    }
    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_claim_without_refund_details_is_judged_without_evidence() -> None:
    message = _make_message(BODY_WITHOUT_REFUND_DETAILS)
    db_session = _make_db_session()

    with _pipeline() as mocks:
        from src.worker.worker import process_message
        await process_message(message, db_session)

    mocks["evidence"].assert_not_awaited()
    assert "evidence" not in mocks["judge"].await_args.kwargs["context"]
    assert "evidence" not in _locked_row(db_session).judge_trail


@pytest.mark.asyncio
async def test_no_db_transaction_is_held_open_while_evidence_and_judges_run() -> None:
    """Retrieval opens a read transaction; it must end before the slow MCP
    and LLM calls, not stay "idle in transaction" until the final write."""
    message = _make_message(BODY)
    db_session = _make_db_session()
    rollbacks_seen: list[int] = []

    async def judge(**_: Any) -> dict[str, Any]:
        rollbacks_seen.append(db_session.rollback.await_count)
        return APPROVE

    async def evidence(*_: Any) -> EvidenceCheck:
        rollbacks_seen.append(db_session.rollback.await_count)
        return PASSED_EVIDENCE

    with _pipeline() as mocks:
        mocks["judge"].side_effect = judge
        mocks["evidence"].side_effect = evidence
        from src.worker.worker import process_message
        await process_message(message, db_session)

    assert rollbacks_seen == [1, 1]


@pytest.mark.asyncio
async def test_a_failed_evidence_claim_trace_ends_with_the_reason(trace_exporter) -> None:
    from tests.support.tracing import finished_spans, is_child_of, span_attr

    with _pipeline(evidence=FAILED_EVIDENCE):
        from src.worker.worker import process_message
        await process_message(_make_message(BODY), _make_db_session())

    spans = finished_spans(trace_exporter)
    root = spans["process-claim"]
    check = spans["verify-evidence"]
    assert is_child_of(check, root)
    assert span_attr(check, "langfuse.observation.type") == "guardrail"
    output = span_attr(root, "langfuse.observation.output")
    assert '"status": "PENDING_HUMAN_REVIEW"' in output
    assert "exceeds what remains refundable" in output


# ── Broker restart mid-message (found by the chaos/idempotency test) ─────────


@pytest.mark.asyncio
async def test_ack_on_a_closed_channel_does_not_crash_or_nack() -> None:
    """RabbitMQ restarted while this message was in flight: the ack can't be
    sent. The broker redelivers it and idempotency absorbs the replay, so the
    worker must log and move on, not raise out of process_message."""
    from aiormq.exceptions import ChannelInvalidStateError

    message = _make_message(BODY)
    message.ack = AsyncMock(side_effect=ChannelInvalidStateError())
    db_session = _make_db_session()

    with _pipeline():
        from src.worker.worker import process_message
        await process_message(message, db_session)

    message.nack.assert_not_awaited()
    assert _locked_row(db_session).status == "COMPLETED"


@pytest.mark.asyncio
async def test_nack_on_a_closed_channel_does_not_crash() -> None:
    from aiormq.exceptions import ChannelInvalidStateError

    message = _make_message(BODY)
    message.nack = AsyncMock(side_effect=ChannelInvalidStateError())
    db_session = _make_db_session()

    with _pipeline(executor_error=RefundExecutionError("mcp down")):
        from src.worker.worker import process_message
        await process_message(message, db_session)

    message.nack.assert_awaited_once_with(requeue=False)


@pytest.mark.asyncio
async def test_handle_delivery_survives_a_channel_closed_on_settle() -> None:
    """message.process() settles an unsettled message on exit; with the channel
    gone, that raises too. The consume loop must survive it."""
    from aiormq.exceptions import ChannelInvalidStateError

    from src.worker.worker import handle_delivery

    message = _make_message(BODY)
    process_ctx = MagicMock()
    process_ctx.__aenter__ = AsyncMock()
    process_ctx.__aexit__ = AsyncMock(side_effect=ChannelInvalidStateError())
    message.process = MagicMock(return_value=process_ctx)
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=_make_db_session())
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    session_maker = MagicMock(return_value=session_ctx)

    with _pipeline():
        await handle_delivery(message, session_maker)

    message.process.assert_called_once_with(ignore_processed=True)


# ── Langfuse trace of one claim ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_claim_is_one_trace_with_retrieval_and_refund_nested(trace_exporter) -> None:
    from langfuse import Langfuse

    from tests.support.tracing import finished_spans, is_child_of, span_attr

    message = _make_message(BODY)
    with _pipeline(retrieved_policy="Refunds within 30 days."):
        from src.worker.worker import process_message
        await process_message(message, _make_db_session())

    spans = finished_spans(trace_exporter)
    root = spans["process-claim"]
    assert f"{root.context.trace_id:032x}" == Langfuse.create_trace_id(seed="req-test-001")
    assert "I need a refund of 50 dollars." in span_attr(root, "langfuse.observation.input")
    assert '"status": "COMPLETED"' in span_attr(root, "langfuse.observation.output")

    retrieval = spans["retrieve-policy"]
    assert is_child_of(retrieval, root)
    assert span_attr(retrieval, "langfuse.observation.type") == "retriever"
    assert "Refunds within 30 days." in span_attr(retrieval, "langfuse.observation.output")

    refund = spans["execute-refund"]
    assert is_child_of(refund, root)
    assert span_attr(refund, "langfuse.observation.type") == "tool"
    assert '"status": "executed"' in span_attr(refund, "langfuse.observation.output")


@pytest.mark.asyncio
async def test_a_blocked_claim_trace_ends_with_the_blocked_status(trace_exporter) -> None:
    from tests.support.tracing import finished_spans, span_attr

    blocked = GuardResult(status="blocked", score=0.999)
    with _pipeline(guard=blocked):
        from src.worker.worker import process_message
        await process_message(_make_message(BODY), _make_db_session())

    spans = finished_spans(trace_exporter)
    output = span_attr(spans["process-claim"], "langfuse.observation.output")
    assert '"status": "BLOCKED_MALICIOUS_PROMPT"' in output
    assert "execute-refund" not in spans


@pytest.mark.asyncio
async def test_a_failed_refund_is_an_error_on_its_tool_observation(trace_exporter) -> None:
    from tests.support.tracing import finished_spans, span_attr

    with _pipeline(executor_error=RefundExecutionError("MCP unreachable")):
        from src.worker.worker import process_message
        await process_message(_make_message(BODY), _make_db_session())

    spans = finished_spans(trace_exporter)
    assert span_attr(spans["execute-refund"], "langfuse.observation.level") == "ERROR"
    assert '"status": "EXECUTION_FAILED"' in span_attr(
        spans["process-claim"], "langfuse.observation.output"
    )
