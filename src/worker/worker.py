import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.judge import evaluate_decision
from src.agents.llm_factory import get_embeddings, get_llm
from src.agents.prompt_guard import GuardResult, scan_for_injection
from src.core.config import settings
from src.core.currency import Currency
from src.core.models import Transaction
from src.core.services.retrieval_service import retrieve_relevant_policy
from src.worker.refund_executor import (
    McpCallPolicy,
    RefundExecutionError,
    execute_refund_via_mcp,
)

logger = logging.getLogger(__name__)


async def process_message(message: Any, db_session: AsyncSession) -> None:
    """Process an incoming RabbitMQ message with strict concurrency control.

    Uses an atomic INSERT as the distributed claim mechanism. On IntegrityError,
    another worker already owns the row — ACK and discard without LLM invocation.
    Final status write uses SELECT FOR UPDATE (pessimistic lock) to prevent
    concurrent updates to the same row.
    """
    try:
        body = json.loads(message.body.decode())
        request_id = body.get("request_id")

        if not request_id:
            logger.warning("Message missing request_id")
            await message.ack()
            return

        # ── Step 1: Atomic INSERT claim ─────────────────────────────────────
        # The INSERT itself is the distributed lock. If two workers race on the
        # same request_id, PostgreSQL's UniqueConstraint ensures only one succeeds.
        # The loser gets IntegrityError and discards safely.
        try:
            txn = Transaction(request_id=request_id, payload=body, status="PROCESSING")
            db_session.add(txn)
            await db_session.flush()   # send INSERT; raises IntegrityError on duplicate
            await db_session.commit()
            logger.info(f"Transaction {request_id} claimed with status PROCESSING")
        except IntegrityError:
            await db_session.rollback()
            logger.warning(
                f"Race condition evadida: request_id={request_id} already owned "
                "by another worker. Discarding."
            )
            await message.ack()
            return

        # ── Step 2: Pre-Execution Shield (Prompt Guard) ─────────────────────
        claim_text = body.get("claim_text", "")
        guard_result: GuardResult | None = None
        if claim_text:
            guard_result = await scan_for_injection(claim_text)
            if guard_result.is_injection:
                # Acquire row lock before updating status
                res = await db_session.execute(
                    select(Transaction)
                    .where(Transaction.request_id == request_id)
                    .with_for_update()
                )
                locked_txn = res.scalar_one()
                locked_txn.status = "BLOCKED_MALICIOUS_PROMPT"
                locked_txn.judge_trail = {"prompt_guard": guard_result.to_trail()}
                await db_session.commit()
                logger.warning(f"🚫 Transaction {request_id} blocked: malicious prompt detected.")
                await message.ack()
                return

        # ── Step 2.5: Retrieval (Phase 1.D RAG, provider-agnostic) ──────────
        # Best-effort: a retrieval/embeddings failure must never block
        # transaction processing (same fail-open principle as prompt_guard.py).
        # Once the primary agent's own LangChain loop exists (still mocked
        # below), this is what its system prompt should be built from; today
        # the Double Judge's `context` is the only real LLM call site
        # available to carry it, so that's where it's threaded in.
        retrieved_policy: str | None = None
        if claim_text:
            try:
                embeddings_client = get_embeddings()
                retrieved_policy = await retrieve_relevant_policy(
                    db_session, embeddings_client, claim_text
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Retrieval skipped for {request_id}: {e}")

        # Instantiate LLM
        _ = get_llm()

        # ── Step 3: Self-Correction Loop ────────────────────────────────────
        retries = 0
        max_retries = settings.MAX_LLM_RETRIES
        judge_result: dict[str, Any] = {}

        judge_context: dict[str, Any] = {"request_id": request_id}
        if retrieved_policy:
            judge_context["retrieved_policy"] = retrieved_policy

        while retries < max_retries:
            # In the real system this invokes the LangChain agent loop.
            mock_primary_action = "execute_refund"
            mock_primary_args = body

            judge_result = await evaluate_decision(
                action_name=mock_primary_action,
                action_args=mock_primary_args,
                context=judge_context,
            )

            if judge_result.get("verdict") == "APPROVE":
                break
            else:
                retries += 1
                logger.warning(
                    f"⚠️  Judge rejected (attempt {retries}/{max_retries}). "
                    f"Reason: {judge_result.get('reason')}"
                )

        # ── Step 4: Deterministic execution via MCP ─────────────────────────
        # The LLM never pushes the button: only this code calls execute_refund,
        # and only after the judges approve. The call goes through the Phase
        # 1.B security boundary, with request_id as the tool's idempotency key.
        approved = judge_result.get("verdict") == "APPROVE"
        execution: dict[str, Any] | None = None
        final_status = "PENDING_HUMAN_REVIEW"
        order_id = body.get("order_id")
        amount = body.get("amount")

        if approved and not (order_id and amount):
            execution = {
                "status": "not_executable",
                "reason": "Claim approved but has no order_id/amount to refund.",
            }
        elif approved:
            try:
                execution = await execute_refund_via_mcp(
                    request_id=request_id,
                    transaction_id=order_id,
                    amount=amount,
                    currency=body.get("currency") or Currency.USD.value,
                    policy=McpCallPolicy.from_settings(),
                )
                final_status = "COMPLETED"
            except RefundExecutionError as e:
                execution = {"status": "failed", "error": str(e)}
                final_status = "EXECUTION_FAILED"

        # ── Step 5: Pessimistic lock → final status write ───────────────────
        res = await db_session.execute(
            select(Transaction)
            .where(Transaction.request_id == request_id)
            .with_for_update()
        )
        locked_txn = res.scalar_one()
        # A 'skipped' guard (failed open) is recorded here too, so an
        # unscanned claim is never indistinguishable from a clean one.
        trail: dict[str, Any] | None = judge_result.get("trail")
        if guard_result is not None:
            trail = {**(trail or {}), "prompt_guard": guard_result.to_trail()}
        if execution is not None:
            trail = {**(trail or {}), "execution": execution}
        locked_txn.judge_trail = trail
        locked_txn.status = final_status

        if final_status == "COMPLETED":
            logger.info(
                f"✅ Transaction {request_id} APPROVED and refund executed. "
                f"Reason: {judge_result.get('reason')}"
            )
        elif final_status == "EXECUTION_FAILED":
            logger.error(
                f"💥 Transaction {request_id} APPROVED but refund execution failed: "
                f"{execution}"
            )
        elif approved:
            logger.warning(
                f"❌ Transaction {request_id} → PENDING_HUMAN_REVIEW: approved "
                "but not executable (missing order_id/amount)."
            )
        else:
            logger.warning(
                f"❌ Transaction {request_id} → PENDING_HUMAN_REVIEW "
                f"after {max_retries} attempts. Final reason: {judge_result.get('reason')}"
            )

        await db_session.commit()
        logger.info(f"Transaction {request_id} committed to DB with status: {locked_txn.status}")

        if final_status == "EXECUTION_FAILED":
            # Retries are exhausted inside the executor; requeueing would only
            # loop. The row already records the failure for an operator.
            await message.nack(requeue=False)
            return

        await message.ack()

    except Exception as e:  # noqa: BLE001
        logger.error(f"Error processing message: {e}")
        await message.nack(requeue=False)


import asyncio

import aio_pika

from src.core.database import get_engine, get_session_maker


async def start_worker() -> None:
    """
    Connect to RabbitMQ and start consuming messages from agent_tasks_queue.
    """
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)

    async with connection:
        channel = await connection.channel()
        # Without a prefetch limit, RabbitMQ pushes the entire queue backlog to
        # this consumer's local buffer as soon as it subscribes, regardless of
        # how fast process_message() actually drains it. This worker processes
        # one message at a time (see the loop below), so prefetch=1 makes
        # RabbitMQ hand over the next message only once the current one is
        # acked/nacked, instead of flooding the client with a large backlog.
        await channel.set_qos(prefetch_count=1)
        # Ensure the queue exists
        queue = await channel.declare_queue("agent_tasks_queue", durable=True)
        
        # We need a db engine/session maker for the worker lifecycle
        engine = get_engine(settings.DATABASE_URL)
        session_maker = get_session_maker(engine)
        
        logger.info("Worker started, waiting for messages...")
        
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process(ignore_processed=True), \
                           session_maker() as db_session:
                        await process_message(message, db_session)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_worker())
