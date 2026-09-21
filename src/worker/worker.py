import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.judge import evaluate_decision
from src.agents.llm_factory import get_llm
from src.agents.prompt_guard import check_for_injection
from src.core.config import settings
from src.core.models import Transaction

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
        if claim_text:
            is_injection = await check_for_injection(claim_text)
            if is_injection:
                # Acquire row lock before updating status
                res = await db_session.execute(
                    select(Transaction)
                    .where(Transaction.request_id == request_id)
                    .with_for_update()
                )
                locked_txn = res.scalar_one()
                locked_txn.status = "BLOCKED_MALICIOUS_PROMPT"
                await db_session.commit()
                logger.warning(f"🚫 Transaction {request_id} blocked: malicious prompt detected.")
                await message.ack()
                return

        # Instantiate LLM
        _ = get_llm()

        # ── Step 3: MCP + Self-Correction Loop ──────────────────────────────
        async with sse_client(settings.MCP_SERVER_URL) as streams, \
                   ClientSession(streams[0], streams[1]) as mcp_session:
            await mcp_session.initialize()

            retries = 0
            max_retries = settings.MAX_LLM_RETRIES
            judge_result: dict[str, Any] = {}

            while retries < max_retries:
                # In the real system this invokes the LangChain agent loop.
                mock_primary_action = "execute_refund"
                mock_primary_args = body

                judge_result = await evaluate_decision(
                    action_name=mock_primary_action,
                    action_args=mock_primary_args,
                    context={"request_id": request_id},
                )

                if judge_result.get("verdict") == "APPROVE":
                    break
                else:
                    retries += 1
                    logger.warning(
                        f"⚠️  Judge rejected (attempt {retries}/{max_retries}). "
                        f"Reason: {judge_result.get('reason')}"
                    )

        # ── Step 4: Pessimistic lock → final status write ───────────────────
        res = await db_session.execute(
            select(Transaction)
            .where(Transaction.request_id == request_id)
            .with_for_update()
        )
        locked_txn = res.scalar_one()

        if judge_result.get("verdict") == "APPROVE":
            locked_txn.status = "COMPLETED"
            logger.info(
                f"✅ Transaction {request_id} APPROVED. "
                f"Reason: {judge_result.get('reason')}"
            )
        else:
            locked_txn.status = "PENDING_HUMAN_REVIEW"
            logger.warning(
                f"❌ Transaction {request_id} → PENDING_HUMAN_REVIEW "
                f"after {max_retries} attempts. Final reason: {judge_result.get('reason')}"
            )

        await db_session.commit()
        logger.info(f"Transaction {request_id} committed to DB with status: {locked_txn.status}")

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
