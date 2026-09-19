import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.llm_factory import get_llm
from src.core.config import settings
from src.core.models import Transaction

logger = logging.getLogger(__name__)

async def process_message(message: Any, db_session: AsyncSession):
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
        
        # Instantiate LLM
        llm = get_llm()
        
        # Set up MCP connection (Structure only)
        # We will mock the actual execution for this test/step.
        async with sse_client(settings.MCP_SERVER_URL) as streams:
            async with ClientSession(streams[0], streams[1]) as mcp_session:
                await mcp_session.initialize()
                
                # Here the LLM agent would interact with the MCP tools
                # For step 4B, we mock the final response completion.
                # In the real system, this invokes the LangChain agent loop.
                
        # Mark as completed
        txn.status = "COMPLETED"
        await db_session.commit()
        
        # Ack the message
        await message.ack()
        
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        # In a real scenario, check max retries and nack or send to DLQ
        await message.nack(requeue=False)
