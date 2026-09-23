# Agentic MCP Engine: Definitive Execution Runbook

This runbook provides step-by-step instructions to set up, run, and test the Agentic MCP Engine locally from scratch.

## Step 1: Environment Setup

First, configure your environment variables by copying the example file.

```bash
cp .env.example .env
```

Edit the `.env` file and configure `GEMINI_API_KEY` or `OPENAI_API_KEY`. 
*Note: If no API key is configured, the system will default to the `mock` LLM provider for safe local testing without external calls.*

## Step 2: Start the Stack

### Option A — Full containerized stack (recommended)

```bash
docker compose up --build
```

This brings up **8 containers** on the private `agentic_net` network: `postgres` (pgvector), `rabbitmq`, `migrate` (one-shot `alembic upgrade head`, exits 0), `mcp_server`, `worker`, `sweeper`, `gateway`, and `dashboard`. Migrations run automatically — skip Steps 3 and 4 and go to Step 6.

| Service | URL |
|---|---|
| API Gateway (Swagger) | `http://localhost:8000/docs` |
| Ops Dashboard (Streamlit, Phase 4) | `http://localhost:8501` |
| MCP Server (HTTP/SSE, token-protected) | `http://localhost:8080/sse` |
| RabbitMQ management UI | `http://localhost:15672` |

### Option B — Local development (services run from your shell)

Start only the infrastructure in Docker:

```bash
docker compose up -d postgres rabbitmq
```

## Step 3: Database Migrations (Option B only)

Apply the Alembic migrations to create the necessary tables in the PostgreSQL database.

```bash
alembic upgrade head
```

## Step 4: Start the Microservices (Option B only)

Open **separate terminal windows** and start each service:

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

**Terminal 4 (Ops Dashboard, optional):**
```bash
streamlit run src/ui/app.py --server.port=8501
```

## Step 5: Recovery Sweeper (Optional — Recommended in Production)

The Recovery Sweeper is an independent background process that detects and recovers **zombie transactions** — rows stuck in `PROCESSING` status because the worker that claimed them crashed before completing.

In Option A it already runs as the `sweeper` container. In Option B, run it in its own terminal alongside the worker:

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

Easiest path: open the Ops Dashboard (`http://localhost:8501`), submit a claim from the ingestion panel, and watch it move through the transaction monitor — each row expands into the Judge 1 / Judge 2 / Supreme Court reasoning trail.

Or, with all services running, send a test payload to the API Gateway to trigger the end-to-end flow. The API will accept the request and pass it to RabbitMQ, where the worker will pick it up and process it via the MCP Server.

```bash
curl -X POST http://localhost:8000/api/v1/claims \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "test-req-001",
    "user_id": "usr-123",
    "claim_text": "I want to request a refund for my last transaction of 50 dollars."
  }'
```

## Step 7: Database Verification

You can verify that the transaction was processed and recorded idempotently by inspecting the PostgreSQL database.

The dashboard's transaction monitor shows the same data. To inspect the database directly, connect to `localhost:5432` using a database client like **DBeaver** or via command line with `psql`. Check the database tables to confirm the `request_id` (`test-req-001`) was inserted successfully. Because of the idempotency checks, sending the exact same `curl` command again will skip reprocessing.

## Step 8: Run the Tests

```bash
# Unit + integration (needs postgres and rabbitmq running)
pytest tests/unit tests/integration --cov=src --cov-report=term-missing
```

Last full run (2026-09-23): 232 passed (182 unit + 50 integration), 84% line coverage over `src/`.

## Step 9: Load Test (Locust)

Against the full containerized stack (Option A):

```bash
locust -f tests/performance/locustfile.py --headless -u 100 -r 10 --run-time 1m --host http://localhost:8000
```

Baseline (2026-09-21): 2,630 requests, 0 failures, P50 55 ms, P95 87 ms. Note that Prompt Guard, Judge 2, and the Supreme Court hardcode their provider and make real API calls for every message the worker drains, regardless of `LLM_PROVIDER` — purge the queue afterward rather than draining thousands of messages if you want to avoid spending quota.
