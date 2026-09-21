import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.judge import evaluate_decision
from src.agents.llm_factory import get_llm
from src.agents.prompt_guard import check_for_injection
from src.core.config import settings
from src.core.models import Transaction

logger = logging.getLogger(__name__)

async def process_message(message: Any, db_session: AsyncSession) -> None:
    """
    Process an incoming RabbitMQ message.
    Ensures idempotency by checking if the request_id is already completed.
    """
    try:
        body = json.loads(message.body.decode())
        request_id = body.get("request_id")
        
        if not request_id:
            logger.warning("Message missing request_id")
            await message.ack()
            return

        # Check for idempotency
        result = await db_session.execute(select(Transaction).where(Transaction.request_id == request_id))
        txn = result.scalar_one_or_none()
        
        if txn and txn.status == "COMPLETED":
            logger.info(f"Transaction {request_id} already COMPLETED. Acking and skipping.")
            await message.ack()
            return
            
        if not txn:
            txn = Transaction(request_id=request_id, payload=body, status="PENDING")
            db_session.add(txn)
            await db_session.commit()
            
        logger.info(f"Processing transaction {request_id}")
        
        # 1. Pre-Execution Shield (Prompt Guard)
        claim_text = body.get("claim_text", "")
        if claim_text:
            is_injection = await check_for_injection(claim_text)
            if is_injection:
                txn.status = "BLOCKED_MALICIOUS_PROMPT"
                await db_session.commit()
                await message.ack()
                return
        
        # Instantiate LLM
        _ = get_llm()
        
        # Set up MCP connection (Structure only)
        # We will mock the actual execution for this test/step.
        async with sse_client(settings.MCP_SERVER_URL) as streams, \
                   ClientSession(streams[0], streams[1]) as mcp_session:
                await mcp_session.initialize()
                
                # 2. Self-Correction Loop
                retries = 0
                max_retries = settings.MAX_LLM_RETRIES
                
                judge_result = {}
                
                while retries < max_retries:
                    # Here the LLM agent would interact with the MCP tools
                    # For step 5, we mock the final primary decision and pass it to the judge.
                    # In the real system, this invokes the LangChain agent loop.
                    mock_primary_action = "execute_refund"
                    mock_primary_args = body
            
                    # Evaluate with the Guardrail Judge
                    judge_result = await evaluate_decision(
                        action_name=mock_primary_action,
                        action_args=mock_primary_args,
                        context={"request_id": request_id}
                    )
                    
                    if judge_result.get("verdict") == "APPROVE":
                        txn.status = "COMPLETED"
                        logger.info(
                            f"✅ Transaction {request_id} APPROVED. "
                            f"Reason: {judge_result.get('reason')}"
                        )
                        break
                    else:
                        retries += 1
                        logger.warning(
                            f"⚠️  Judge rejected (attempt {retries}/{max_retries}). "
                            f"Reason: {judge_result.get('reason')}"
                        )
                        # In real system, feed judge_result['reason'] back into the agent loop here
                
                if judge_result.get("verdict") != "APPROVE":
                    txn.status = "PENDING_HUMAN_REVIEW"
                    logger.warning(
                        f"❌ Transaction {request_id} → PENDING_HUMAN_REVIEW "
                        f"after {max_retries} attempts. Final reason: {judge_result.get('reason')}"
                    )

        await db_session.commit()
        logger.info(f"Transaction {request_id} committed to DB with status: {txn.status}")

        # Ack the message
        await message.ack()
        
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error processing message: {e}")
        # In a real scenario, check max retries and nack or send to DLQ
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
