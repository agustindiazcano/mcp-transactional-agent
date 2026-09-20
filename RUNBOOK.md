# Agentic MCP Engine: Definitive Execution Runbook

This runbook provides step-by-step instructions to set up, run, and test the Agentic MCP Engine locally from scratch.

## Step 1: Environment Setup

First, configure your environment variables by copying the example file.

```bash
cp .env.example .env
```

Edit the `.env` file and configure `GEMINI_API_KEY` or `OPENAI_API_KEY`. 
*Note: If no API key is configured, the system will default to the `mock` LLM provider for safe local testing without external calls.*

## Step 2: Infrastructure

Start the required infrastructure (PostgreSQL and RabbitMQ) using Docker Compose in detached mode.

```bash
docker compose up -d
```

## Step 3: Database Migrations

Apply the Alembic migrations to create the necessary tables in the PostgreSQL database.

```bash
alembic upgrade head
```

## Step 4: Start the Microservices

The architecture consists of three decoupled services. Open **three separate terminal windows** and start each one:

**Terminal 1 (API Gateway):**
```bash
uvicorn src.api.main:app --port 8000
```

**Terminal 2 (MCP Server):**
```bash
uvicorn src.mcp_server.mcp_server:app --port 8080
```

**Terminal 3 (Asynchronous Worker):**
```bash
python -m src.worker.worker
```

## Step 5: Send a Test Prompt (E2E Flow)

With all services running, send a test payload to the API Gateway to trigger the end-to-end flow. The API will accept the request and pass it to RabbitMQ, where the worker will pick it up and process it via the MCP Server.

```bash
curl -X POST http://localhost:8000/api/v1/claims \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "test-req-001",
    "user_id": "usr-123",
    "text": "I want to request a refund for my last transaction of 50 dollars."
  }'
```

## Step 6: Database Verification

You can verify that the transaction was processed and recorded idempotently by inspecting the PostgreSQL database. 

Connect to `localhost:5432` using a database client like **DBeaver** or via command line with `psql`. Check the database tables to confirm the `request_id` (`test-req-001`) was inserted successfully. Because of the idempotency checks, sending the exact same `curl` command again will skip reprocessing.
