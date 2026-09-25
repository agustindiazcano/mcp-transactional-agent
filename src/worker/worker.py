import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.front_desk import propose_action
from src.agents.judge import evaluate_decision
from src.agents.llm_factory import get_embeddings, get_llm, resolve_provider
from src.agents.prompt_guard import GuardResult, scan_for_injection
from src.agents.proposal import ClaimProposal
from src.core.config import settings
from src.core.currency import Currency
from src.core.models import Transaction
from src.core.services.retrieval_service import retrieve_relevant_policy
from src.core.tracing import claim_trace, observe, shutdown_tracing
from src.worker.amqp import CHANNEL_GONE_ERRORS, connect_with_retry, safe_ack, safe_nack
from src.worker.evidence import EvidenceUnavailableError, verify_claim_evidence
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
            await safe_ack(message)
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
            await safe_ack(message)
            return

        # One Langfuse trace per claim, opened only once this worker owns the
        # row (a discarded duplicate adds nothing to it). Tracing never changes
        # the outcome: with no keys, or if Langfuse fails, it is a no-op.
        with claim_trace(
            request_id,
            user_id=str(body.get("user_id", "")),
            input={
                "claim_text": body.get("claim_text", ""),
                "order_id": body.get("order_id"),
                "amount": body.get("amount"),
                "currency": body.get("currency"),
            },
            tags=[f"llm-provider:{settings.LLM_PROVIDER}"],
        ) as trace:
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
                    trace.update(output={"status": "BLOCKED_MALICIOUS_PROMPT"})
                    await safe_ack(message)
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
                    embeddings_provider = resolve_provider()
                    with observe(
                        "retrieve-policy",
                        as_type="retriever",
                        input=claim_text,
                        metadata={"provider": embeddings_provider, "top_k": 1},
                    ) as retrieval:
                        embeddings_client = get_embeddings(embeddings_provider)
                        retrieved_policy = await retrieve_relevant_policy(
                            db_session, embeddings_client, claim_text, provider=embeddings_provider
                        )
                        retrieval.update(output=retrieved_policy)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Retrieval skipped for {request_id}: {e}")

            # End the read transaction retrieval opened: nothing was written
            # since the claim's commit, and the MCP and LLM calls below take
            # seconds. The final write opens its own transaction.
            await db_session.rollback()

            judge_context: dict[str, Any] = {"request_id": request_id}
            if retrieved_policy:
                judge_context["retrieved_policy"] = retrieved_policy

            # ── Step 2.55: Front-Desk proposal (Phase 1.E, intent gate) ─────────
            # propose_action() replaces the hardcoded mock_primary_action: the
            # primary agent's own classification of the claim decides whether
            # there is a refund to evaluate at all. A non-refund intent
            # (clarify/out_of_scope) is never evidence-checked or judged --
            # there is nothing yet to check or approve. Intent gate only
            # (2026-09-25 decision): when it *is* a refund, the proposal's own
            # order_id/amount/currency are not used as the source of truth --
            # the claim's own structured fields, already validated at the
            # gateway, still drive evidence and execution, unchanged from
            # before this phase.
            proposal: ClaimProposal | None = None
            front_desk_reason: str | None = None
            front_desk_intent: str | None = None
            if claim_text:
                proposal = await propose_action(claim_text)
                if proposal.intent != "refund":
                    front_desk_reason = proposal.reason
                    front_desk_intent = proposal.intent

            # ── Step 2.6: Evidence check (Part B) ───────────────────────────────
            # Code, not a judge, checks the order and the refund history. A
            # failure (or an MCP outage) goes to human review with no LLM call:
            # the check can stop an approval, never grant one.
            evidence_trail: dict[str, Any] | None = None
            evidence_failure: str | None = None
            if front_desk_reason is None and body.get("order_id") and body.get("amount"):
                with observe(
                    "verify-evidence",
                    as_type="guardrail",
                    input={
                        "order_id": body.get("order_id"),
                        "amount": body.get("amount"),
                        "currency": body.get("currency"),
                    },
                ) as verification:
                    try:
                        evidence = await verify_claim_evidence(body, McpCallPolicy.from_settings())
                    except EvidenceUnavailableError as e:
                        evidence_trail = {"status": "unavailable", "error": str(e)}
                        evidence_failure = f"Evidence unavailable: {e}"
                        verification.update(
                            output=evidence_trail, level="ERROR", status_message=str(e)
                        )
                    else:
                        evidence_trail = evidence.to_trail()
                        verification.update(output=evidence_trail)
                        if evidence.passed:
                            judge_context["evidence"] = evidence.summary_for_judges()
                        else:
                            evidence_failure = " ".join(evidence.failures)

            # Instantiate LLM
            _ = get_llm()

            # ── Step 3: Self-Correction Loop ────────────────────────────────────
            # The primary agent's proposal is still hardcoded (Phase 1.E is not
            # implemented yet): the action itself is still the fixed
            # "execute_refund"/body pair on every attempt (the Front-Desk
            # gates intent only, see Step 2.55), so there is nothing for a
            # retry to correct. Re-asking the identical question to the same
            # judge ensemble until it happens to say APPROVE is a re-vote, not
            # self-correction -- with verdicts that aren't perfectly stable
            # between runs (docs/testing/judge_evaluation_results.md), that
            # would only inflate the false-approval rate. So this evaluates
            # the proposal exactly once. Once Phase 1.E's self-correction loop
            # can revise the proposal from judge feedback, this becomes a
            # real loop again: retry only when the new proposal actually
            # differs from the one just rejected, up to MAX_LLM_RETRIES.
            judge_result: dict[str, Any] = {}
            retry_proposal: ClaimProposal | None = None

            if evidence_failure is None and front_desk_reason is None:
                action_name = "execute_refund"
                action_args = body

                judge_result = await evaluate_decision(
                    action_name=action_name,
                    action_args=action_args,
                    context=judge_context,
                )

                if judge_result.get("verdict") != "APPROVE":
                    logger.warning(
                        f"⚠️  Judge rejected. Reason: {judge_result.get('reason')}"
                    )

                    # ── Step 3.5: Front-Desk reclassification (self-correction) ──
                    # Narrow scope (2026-09-25 decision): a REJECT can't change
                    # what the judges just evaluated -- action_args is still the
                    # claim's own body, per Step 2.55's intent-gate-only design
                    # -- so re-running the same judges on the same args would be
                    # exactly the re-vote this file has always refused to do
                    # (see Step 3's comment). What a REJECT *can* change is
                    # whether the claim was correctly classified as a refund at
                    # all: the Front-Desk gets exactly one more look, told why a
                    # specialist rejected it. If it now says clarify/
                    # out_of_scope, that reclassification -- not the raw judge
                    # rationale -- becomes the human-review reason, matching the
                    # Feedback Loop's "never a raw judge rationale" contract
                    # (Section 5a-iv, item 3). If it still says refund, there is
                    # nothing new to act on and the judges are not called again.
                    reclassification = await propose_action(
                        claim_text, rejection_feedback=judge_result.get("reason")
                    )
                    if reclassification.intent != "refund":
                        retry_proposal = reclassification
                        front_desk_reason = reclassification.reason
                        front_desk_intent = reclassification.intent

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
                currency = body.get("currency") or Currency.USD.value
                try:
                    with observe(
                        "execute-refund",
                        as_type="tool",
                        input={"transaction_id": order_id, "amount": amount, "currency": currency},
                        metadata={"idempotency_key": request_id},
                    ) as refund:
                        execution = await execute_refund_via_mcp(
                            request_id=request_id,
                            transaction_id=order_id,
                            amount=amount,
                            currency=currency,
                            policy=McpCallPolicy.from_settings(),
                        )
                        refund.update(output=execution)
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
            if proposal is not None:
                trail = {**(trail or {}), "front_desk": proposal.model_dump()}
            if retry_proposal is not None:
                trail = {**(trail or {}), "front_desk_retry": retry_proposal.model_dump()}
            if evidence_trail is not None:
                trail = {**(trail or {}), "evidence": evidence_trail}
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
            elif front_desk_reason is not None and retry_proposal is not None:
                logger.warning(
                    f"❌ Transaction {request_id} → PENDING_HUMAN_REVIEW: judge "
                    f"rejected, and the Front-Desk reclassified as "
                    f"intent={front_desk_intent!r} on review. Reason: {front_desk_reason}"
                )
            elif front_desk_reason is not None:
                logger.warning(
                    f"❌ Transaction {request_id} → PENDING_HUMAN_REVIEW: Front-Desk "
                    f"proposed intent={front_desk_intent!r} (not a refund), judges not "
                    f"called. Reason: {front_desk_reason}"
                )
            elif evidence_failure is not None:
                logger.warning(
                    f"❌ Transaction {request_id} → PENDING_HUMAN_REVIEW: evidence check "
                    f"failed, judges not called. Reason: {evidence_failure}"
                )
            elif approved:
                logger.warning(
                    f"❌ Transaction {request_id} → PENDING_HUMAN_REVIEW: approved "
                    "but not executable (missing order_id/amount)."
                )
            else:
                logger.warning(
                    f"❌ Transaction {request_id} → PENDING_HUMAN_REVIEW. "
                    f"Final reason: {judge_result.get('reason')}"
                )

            await db_session.commit()
            logger.info(f"Transaction {request_id} committed to DB with status: {locked_txn.status}")
            trace.update(
                output={
                    "status": final_status,
                    "reason": front_desk_reason or evidence_failure or judge_result.get("reason"),
                },
                metadata={
                    "judge_attempts": 1 if judge_result else 0,
                },
            )

            if final_status == "EXECUTION_FAILED":
                # Retries are exhausted inside the executor; requeueing would only
                # loop. The row already records the failure for an operator.
                await safe_nack(message, requeue=False)
                return

            await safe_ack(message)

    except Exception as e:  # noqa: BLE001
        logger.error(f"Error processing message: {e}")
        await safe_nack(message, requeue=False)


import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.database import get_engine, get_session_maker


async def handle_delivery(message: Any, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Process one delivery, surviving a channel that closed under it.

    message.process() settles a still-unsettled message on exit. If RabbitMQ
    restarted mid-message, that settle raises too; the broker redelivers the
    message and idempotency absorbs it, so the consume loop just moves on.
    """
    try:
        async with message.process(ignore_processed=True), session_maker() as db_session:
            await process_message(message, db_session)
    except CHANNEL_GONE_ERRORS as exc:
        logger.warning(f"Channel closed while settling a message ({exc!r}); it will be redelivered.")


async def start_worker() -> None:
    """
    Connect to RabbitMQ and start consuming messages from agent_tasks_queue.
    """
    connection = await connect_with_retry(settings.RABBITMQ_URL)

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
                await handle_delivery(message, session_maker)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(start_worker())
    finally:
        # Export the spans still queued in the background, then stop.
        shutdown_tracing()
