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

## Step 5: Recovery Sweeper (Optional — Recommended in Production)

The Recovery Sweeper is an independent background process that detects and recovers **zombie transactions** — rows stuck in `PROCESSING` status because the worker that claimed them crashed before completing.

Run it in a **fourth terminal** alongside the worker:

```bash
python -m src.worker.recovery_sweeper
```

The sweeper polls every `SWEEPER_INTERVAL_SECONDS` (default: 300s). For local testing you can lower this in `.env`:

```env
SWEEPER_INTERVAL_SECONDS=30
SWEEPER_STALE_THRESHOLD_SECONDS=60
```

To simulate a zombie and test recovery:
1. Send a POST request to create a transaction.
2. Kill the worker (`Ctrl+C`) immediately after it logs `"claimed with status PROCESSING"`.
3. Wait for the sweeper to detect and re-enqueue the row.
4. Restart the worker — it will process the recovered message cleanly.

> **Why `FOR UPDATE SKIP LOCKED`?** The sweeper uses PostgreSQL's `SKIP LOCKED` hint to non-destructively iterate stale rows. If a live worker still holds a lock on a `PROCESSING` row (e.g., a slow LLM call), the sweeper skips that row without blocking — eliminating the risk of deadlocks.

## Step 6: Send a Test Prompt (E2E Flow)

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

## Step 7: Database Verification

You can verify that the transaction was processed and recorded idempotently by inspecting the PostgreSQL database.

Connect to `localhost:5432` using a database client like **DBeaver** or via command line with `psql`. Check the database tables to confirm the `request_id` (`test-req-001`) was inserted successfully. Because of the idempotency checks, sending the exact same `curl` command again will skip reprocessing.
