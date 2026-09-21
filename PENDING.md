# 📝 Roadmap: Agentic MCP Engine

Personal working notes. See README.md's Roadmap table and Phase sections for the canonical, detailed version of all of this — this file is the short, checklist-style view, kept in explicit priority order.

## Priority Order

### Step 1 — Load & Chaos Testing with Locust (Phase 1.C) — blocked on an open MCP bug
Full investigation trail: [docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md](docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md).

Attempted for real against the full `docker compose` stack. The Gateway/queue path itself works (2592 reqs, 0 failures, P50=75ms, P95=340ms once the queue wasn't backlogged), but the Worker→MCP session — needed to actually reach the final `SELECT FOR UPDATE` write this step exists to validate — fails. Found and fixed two real bugs in the process (see git log `4691f17`): the MCP SDK's Host-header allowlist didn't include the Docker Compose service name (`mcp_server:8080`), and `message_path` was missing its required trailing slash, causing a redirect the client doesn't follow. A **third** MCP transport bug remains open: a real transaction (run as the container's actual entrypoint process) still fails intermittently with `httpx2.RemoteProtocolError: peer closed connection without sending complete message body` while awaiting the SSE-delivered `initialize()` response. Every isolated reproduction attempt (sequential/concurrent connections, with a real aio-pika connection, the exact `queue.iterator()`+`message.process()` pattern, via `docker exec` inside the same container, with/without backlog, with/without Locust load) succeeded — only the real entrypoint process fails. Root cause not identified after extensive isolated testing; needs a fresh session with fresh eyes, possibly stracing/tcpdumping the actual container process rather than a reproduction.
- [ ] Root-cause and fix the remaining SSE `initialize()` transport failure.
- [ ] Once fixed: re-run the 100+ concurrent load test against the containerized stack and confirm the pessimistic locks hold under contention without deadlocks (not actually validated yet — every transaction in every run so far died before reaching the final lock/write step).
- [ ] Metrics: measure and fill in the README's `System Performance & Telemetry` table with real throughput (req/s) and P95 latency, replacing the placeholder values.

**Side findings from this attempt, not yet fixed:**
- [ ] `prompt_guard.py` hardcodes `provider="groq"` regardless of `LLM_PROVIDER`, and `langchain-groq` isn't in `pyproject.toml`'s dependencies — `ImportError`s inside the container on every call. Caught by its own fail-open handler (not blocking), but means Judge 2 (Groq) cannot actually run in the Docker deployment as currently packaged.
- [ ] `src/api/main.py`'s `/api/v1/claims` handler opens a brand-new `aio_pika.connect_robust()` connection per request instead of reusing one — almost certainly why ingestion latency climbed under sustained load before the queue-backlog issue was found and controlled for.
- [x] No prefetch limit on the Worker's RabbitMQ channel — fixed (`channel.set_qos(prefetch_count=1)`, same commit as above).

### Step 2 — Cost per Transaction Measurement
- [ ] Measure real token consumption per stage (RAG embedding + primary agent + judges).
- [ ] Fill in the README's `Cost per Transaction` table with an exact dollar figure ($0.00XX USD per claim) to demonstrate financial control of the system.

### Step 3 — Zero-Trust MCP Hardening (Phase 1.B)
- [ ] Server-side authentication via cryptographic Bearer Token (SHA-256 hashes), constant-time compare.
- [ ] Per-client tool allowlist authorization.
- [ ] Hard business validation in Pydantic (e.g. reject refunds above `REFUND_MAX_AMOUNT` at the interface level, no matter what the LLM asks for).
- [ ] Rate limiting per client/tool, and an immutable audit table in PostgreSQL (insert-only role).

### Step 4 — Frontend: Admin Ops Dashboard (Phase 4)
Why it's critical: this is what proves the Full-Stack E-commerce profile — without a UI, it's backend-only.
- [ ] React + Vite + TypeScript + Tailwind CSS client consuming the FastAPI endpoints.
- [ ] Real-time transaction grid (PENDING, PROCESSING, APPROVED, REJECTED).
- [ ] RAG detail view (which policy chunk was injected, from Phase 1.D's retrieval).
- [ ] Judges' verdicts (Double Judge + Supreme Court cascade outcome).

### Step 5 — Deterministic Confidence Layer (Phase 2)
- [ ] Integrate the fuzzy-scoring layer and the Belief Rule Base alongside the AI Judge, so critical transactions (`execute_refund`, `validate_fraud_score`) require double approval — probabilistic (LLM judge) *and* symbolic (rule base) — before auto-approving.

### Step 6 — Quality Drift Detection (Phase 3)
- [ ] Implement the async monitor with a statistical filter (EWMA default, CUSUM/Page-Hinkley/Kalman as options) to detect whether model responses are degrading over time. Runs off the critical path — never blocks transaction processing.

### Step 7 — Cloud Deployment / AWS Bedrock (Phase 6)
- [ ] Configure IAM credentials and AWS Bedrock access (least privilege, VPC PrivateLink).
- [ ] Swap the embeddings module to use Amazon Titan instead of Gemini (Phase 1.D's embeddings pipeline was deliberately built provider-agnostic for exactly this swap).
- [ ] Migrate the topology to a $0-cost serverless architecture: AWS API Gateway + AWS SQS + AWS Lambda + serverless PostgreSQL (Neon with pgvector).

### Step 8 — Google Vertex AI (experimental, lower priority)
Google Cloud offers new accounts a $300 USD trial credit for 90 days. The abstract factory (`get_llm` in `src/agents/llm_factory.py`) already supports Vertex AI via `GOOGLE_APPLICATION_CREDENTIALS` — but the agreed Enterprise deployment target is **AWS Bedrock**, the corporate standard for private banking VPCs and effectively $0 on serverless (Step 7). So Vertex stays a lower-priority, opportunistic item to exercise with the free trial credit while it's available, not the actual deployment target.
- [ ] Exercise/validate the existing Vertex AI provider branch against real credentials while the trial credit is available.

---

## Already done (not repeated above — see README.md for full detail)
- Phase 1 core engine: event-driven pipeline, MCP server, idempotency, Double Judge, Prompt Guard, self-correction loop, Supreme Court cascade judge, pessimistic locking + Recovery Sweeper.
- Phase 1.C, mostly: per-service Dockerfiles, full `docker-compose` orchestration (7 services), HTTP reachability validated. A real transaction through the stack is not yet reliable (open MCP bug) and load validation (Step 1, above) is blocked on it.
- **Phase 1.D, fully: RAG — common pattern, not tied to Bedrock.** `pgvector` extension + `knowledge_base` table (Alembic migration `7da4609fe11c`); `scripts/ingest_knowledge_base.py` chunks `docs/policies/refund_policy.md` and embeds it via Gemini `gemini-embedding-001` (truncated to 768 dims); the Worker runs a real cosine-similarity search (`embedding <=> claim_vector`, pgvector's `<=>` operator — not `<->`, which is L2/Euclidean distance, a mistake caught and fixed while implementing this) and injects the matched policy into the Double Judge's context, fail-open on any retrieval error. Validated end-to-end against the real Gemini API and a real Postgres. The Bedrock/Titan swap stays deferred to Step 7 (Phase 6).
- `mypy --strict` and the unit test suite are green.
