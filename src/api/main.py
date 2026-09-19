import os
from typing import Any

import aio_pika
from fastapi import FastAPI, status

from src.api.schemas import ClaimRequest

app = FastAPI(title="Agentic MCP Engine API")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

@app.post("/api/v1/claims", status_code=status.HTTP_202_ACCEPTED)
async def create_claim(request: ClaimRequest) -> dict[str, Any]:
    # Connect to RabbitMQ
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    
    async with connection:
        channel = await connection.channel()
        # Declare the queue (so it exists)
        await channel.declare_queue("agent_tasks_queue", durable=True)
        
        # Serialize the message
        message_body = request.model_dump_json().encode("utf-8")
        
        # Publish
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=message_body,
                content_type="application/json"
            ),
            routing_key="agent_tasks_queue",
        )
        
    return {"status": "Accepted", "request_id": request.request_id}
