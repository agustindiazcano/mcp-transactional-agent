# 📝 Roadmap: Agentic MCP Engine

Personal working notes. See README.md's Roadmap table and Phase sections for the canonical, detailed version of all of this — this file is the short, checklist-style view, kept in explicit priority order.

## Priority Order

### Step 1 — Load & Chaos Testing with Locust (Phase 1.C) — root cause fixed; container/load verification pending
Full investigation trail: [docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md](docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md). General practice that found it: [docs/architecture/microservices_debugging_protocol.md](docs/architecture/microservices_debugging_protocol.md).

Attempted for real against the full `docker compose` stack. The Gateway/queue path itself works (2592 reqs, 0 failures, P50=75ms, P95=340ms once the queue wasn't backlogged), but the Worker→MCP session — needed to actually reach the final `SELECT FOR UPDATE` write this step exists to validate — failed on nearly every transaction. Found and fixed two real MCP transport bugs in the process (see git log `4691f17`): the MCP SDK's Host-header allowlist didn't include the Docker Compose service name (`mcp_server:8080`), and `message_path` was missing its required trailing slash, causing a redirect the client doesn't follow. The actual blocker turned out **not to be a transport bug at all**: `src/agents/judge.py`'s `evaluate_decision()` calls `get_llm(provider="groq", ...)` unguarded, `langchain-groq` isn't a declared dependency, and the resulting `ImportError` — raised while inside the MCP session's `async with` block — gets reported by anyio's `TaskGroup` as a generic transport failure (`RemoteProtocolError`/`unhandled errors in a TaskGroup`), which is why extensive isolated MCP-only reproduction attempts never caught it.
- [x] Apply the fix: add `langchain-groq` to `pyproject.toml` (done, `fix/judge-groq-import-crash`, commit `79179f9`). Also refactored `_run_single_judge()` to construct its LLM inside its existing `try/except`, so a construction failure fails closed to `REJECT` instead of crashing — see the postmortem's "Resolution" section. Unit-tested (`tests/unit/test_judge.py`); the "rebuild the `worker` image and verify a real transaction completes cleanly end-to-end" half of this item is still open, tracked below.
- [ ] Rebuild the `worker` image (`docker compose build --no-cache worker`) and verify a real transaction completes end-to-end with no `TaskGroup`/`RemoteProtocolError` in the logs.
- [x] Revert the temporary `traceback.print_exception(...)` debug block in `worker.py` — moot; it was never committed (local-only, stashed on `feat/concurrency-pessimistic-lock`).
- [x] Decide whether `evaluate_decision()`'s Groq dependency should be hard-required or degrade like `prompt_guard.py` does — decided: hard-required *and* defense-in-depth fail-closed to `REJECT`, not fail-open (see postmortem).
- [ ] Once container-verified: re-run the 100+ concurrent load test against the containerized stack and confirm the pessimistic locks hold under contention without deadlocks (not actually validated yet — every transaction in every run so far died before reaching the final lock/write step).
- [ ] Metrics: measure and fill in the README's `System Performance & Telemetry` table with real throughput (req/s) and P95 latency, replacing the placeholder values.

**Side findings from this attempt, not yet fixed:**
- [ ] `prompt_guard.py` hardcodes `provider="groq"` regardless of `LLM_PROVIDER`. The undeclared-dependency crash risk is now closed (`langchain-groq` is declared, so this call actually runs instead of always hitting the fail-open path) — but it still ignores `LLM_PROVIDER`, which is a separate design question, not fixed here.
- [x] `src/api/main.py`'s `/api/v1/claims` handler opened a brand-new `aio_pika.connect_robust()` connection per request instead of reusing one — almost certainly why ingestion latency climbed under sustained load before the queue-backlog issue was found and controlled for. Fixed (`fix/gateway-amqp-connection-pooling`, commit `b1791ce`): the connection/channel are now opened once via a FastAPI `lifespan` and stored on `app.state`, matching the pattern `worker.py`/`recovery_sweeper.py` already use. Unit-tested (`tests/integration/test_api.py`); actual latency-under-load improvement still needs the Locust re-run in Step 1 to confirm.
- [ ] Integration test `tests/integration/test_knowledge_base_repository.py`'s `Base.metadata.drop_all()` teardown silently desyncs the dev DB schema from `alembic_version` — cost real debugging time this session.
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
- Phase 1.C, mostly: per-service Dockerfiles, full `docker-compose` orchestration (7 services), HTTP reachability validated. A real transaction through the stack was not reliable — root cause identified and fixed at the code level, unit-tested (Step 1, above); container rebuild + a real end-to-end transaction, and load validation, are still pending.
- **Phase 1.D, fully: RAG — common pattern, not tied to Bedrock.** `pgvector` extension + `knowledge_base` table (Alembic migration `7da4609fe11c`); `scripts/ingest_knowledge_base.py` chunks `docs/policies/refund_policy.md` and embeds it via Gemini `gemini-embedding-001` (truncated to 768 dims); the Worker runs a real cosine-similarity search (`embedding <=> claim_vector`, pgvector's `<=>` operator — not `<->`, which is L2/Euclidean distance, a mistake caught and fixed while implementing this) and injects the matched policy into the Double Judge's context, fail-open on any retrieval error. Validated end-to-end against the real Gemini API and a real Postgres. The Bedrock/Titan swap stays deferred to Step 7 (Phase 6).
- `mypy --strict` and the unit test suite are green.
