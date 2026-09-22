from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import aio_pika
from fastapi import FastAPI, Request, status

from src.api.routers import system, transactions
from src.api.schemas import ClaimRequest
from src.core.config import settings
from src.core.database import get_engine, get_session_maker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # One connection/channel for the app's lifetime, instead of a new AMQP
    # handshake per request (see docs/postmortems/2026-09-21-phase-1c-load-
    # test-mcp-transport-failure.md).
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    channel = await connection.channel()
    await channel.declare_queue("agent_tasks_queue", durable=True)
    app.state.rabbitmq_connection = connection
    app.state.rabbitmq_channel = channel

    # One engine/session-maker for the app's lifetime, mirroring the AMQP
    # connection above -- backs the Phase 4 dashboard's read-only endpoints.
    db_engine = get_engine(settings.DATABASE_URL)
    app.state.db_engine = db_engine
    app.state.db_session_maker = get_session_maker(db_engine)

    yield

    await connection.close()
    await db_engine.dispose()


app = FastAPI(title="Agentic MCP Engine API", lifespan=lifespan)
app.include_router(transactions.router)
app.include_router(system.router)


@app.post("/api/v1/claims", status_code=status.HTTP_202_ACCEPTED)
async def create_claim(request: ClaimRequest, http_request: Request) -> dict[str, Any]:
    channel = http_request.app.state.rabbitmq_channel

    message_body = request.model_dump_json().encode("utf-8")

    await channel.default_exchange.publish(
        aio_pika.Message(
            body=message_body,
            content_type="application/json"
        ),
        routing_key="agent_tasks_queue",
    )

    return {"status": "Accepted", "request_id": request.request_id}
