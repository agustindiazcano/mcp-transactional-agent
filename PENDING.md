# 📝 Roadmap: Agentic MCP Engine

Personal working notes. See README.md's Roadmap table and Phase sections for the canonical, detailed version of all of this — this file is the short, checklist-style view, kept in explicit priority order.

## Priority Order

### Step 1 — Cost per Transaction Measurement — done, with caveats
- [x] Measure real token consumption per stage (`feat/cost-per-transaction-measurement`, commit `dff32e4`): `src/agents/token_usage.py`'s `extract_usage()` logs a structured `llm_token_usage` line at every real LLM call site (Prompt Guard, Judge 1, Judge 2, Supreme Court), reading `AIMessage.usage_metadata`. Two real gaps surfaced while doing this, both resolved by explicit decision rather than fudged:
  - No real "primary agent" LLM call exists yet — `worker.py`'s tool-calling loop hardcodes its action. That row is N/A in the README, not measured.
  - LangChain's `Embeddings` interface exposes no token usage at all — the retrieval row is a `~4 chars/token` estimate, flagged `estimated=True` in the logs and in the README.
- [x] Fill in the README's `Cost per Transaction` table: a single real transaction (happy path, no Supreme Court escalation) cost **~$0.0004** — see the table for the per-stage breakdown and pricing sources (fetched 2026-09-21). This is a single measurement, not an average, and is the floor (cost scales with self-correction retries and Supreme Court escalations) — re-measure once the primary agent is real and/or averaged across more transactions.

### Step 2 — Zero-Trust MCP Hardening (Phase 1.B) — mostly done, rate limiting remains
- [x] Server-side authentication via cryptographic Bearer Token (SHA-256 hashes), constant-time compare. `src/mcp_server/security/client_registry.py`'s `ClientRegistry.authenticate()`, enforced by `MCPSecurityMiddleware` (an ASGI middleware wrapping the whole `mcp.sse_app()`, gating both the `/sse` handshake and every `/messages/` POST) — missing/invalid token returns 401 before any MCP session starts.
- [x] Per-client tool allowlist authorization. `ClientRegistry.is_allowed()`, checked against the `tools/call` request's `name` before it reaches the MCP server's own dispatch — a disallowed tool returns 403. **Known gap:** `tools/list` visibility isn't filtered by identity (a client can see a tool's name even if it can't call it) — the SSE transport delivers that response asynchronously over the `/sse` stream, outside this POST-request middleware's reach. Execution is still fully gated.
- [x] Hard business validation in Pydantic (reject refunds above `REFUND_MAX_AMOUNT`, unknown currencies, and unknown fields, at the interface level, no matter what the LLM asks for). `src/mcp_server/tools/schemas.py`'s `ExecuteRefundArgs`/`ValidateFraudScoreArgs` (`extra="forbid"`), validated against the raw `tools/call` arguments by `MCPSecurityMiddleware` before the tool function runs — this is stricter than the MCP SDK's own per-parameter schema, which silently drops unknown fields instead of rejecting them.
- [x] Immutable audit table in PostgreSQL. `mcp_audit_logs` (migration `70b40799328f`), written by `src/mcp_server/security/audit.py`'s `write_audit_log()` for every invocation including denied ones (PII-masked arguments). The write gates execution on the allow path — if it fails, the call is denied (503) instead of proceeding (CLAUDE.md's fail-closed rule); a denied call's own audit write is best-effort since the call is already rejected regardless. **Known limitation:** the SSE transport delivers a tool's actual result asynchronously, not as this POST's response, so an ALLOWED row's `result` field records `"invoked"`, not the eventual success/failure. Insert-only by convention in code; a DB role actually restricted to `INSERT`/`SELECT` is an infra follow-up, not yet configured.
- [ ] Rate limiting per client/tool, computed from `mcp_audit_logs` over a sliding window (design unchanged from the original plan — see README's Phase 1.B section). Not started.
- Tests: `tests/unit/security/` (client registry, PII masking, schema validation) and `tests/integration/test_mcp_server.py` (401 on missing/invalid token; over-limit refund blocked + audited; disallowed tool blocked + audited). All passing alongside the full existing suite (76/76) and `ruff`/`mypy --strict` clean (`src/mcp_server/`, `src/core/`, `src/worker/worker.py`).

### Step 3 — Frontend: Admin Ops Dashboard (Phase 4)
Why it's critical: this is what proves the Full-Stack E-commerce profile — without a UI, it's backend-only.
- [ ] React + Vite + TypeScript + Tailwind CSS client consuming the FastAPI endpoints.
- [ ] Real-time transaction grid (PENDING, PROCESSING, APPROVED, REJECTED).
- [ ] RAG detail view (which policy chunk was injected, from Phase 1.D's retrieval).
- [ ] Judges' verdicts (Double Judge + Supreme Court cascade outcome).

### Step 4 — Deterministic Confidence Layer (Phase 2)
- [ ] Integrate the fuzzy-scoring layer and the Belief Rule Base alongside the AI Judge, so critical transactions (`execute_refund`, `validate_fraud_score`) require double approval — probabilistic (LLM judge) *and* symbolic (rule base) — before auto-approving.

### Step 5 — Quality Drift Detection (Phase 3)
- [ ] Implement the async monitor with a statistical filter (EWMA default, CUSUM/Page-Hinkley/Kalman as options) to detect whether model responses are degrading over time. Runs off the critical path — never blocks transaction processing.

### Step 6 — Cloud Deployment / AWS Bedrock (Phase 6)
- [ ] Configure IAM credentials and AWS Bedrock access (least privilege, VPC PrivateLink).
- [ ] Swap the embeddings module to use Amazon Titan instead of Gemini (Phase 1.D's embeddings pipeline was deliberately built provider-agnostic for exactly this swap).
- [ ] Migrate the topology to a $0-cost serverless architecture: AWS API Gateway + AWS SQS + AWS Lambda + serverless PostgreSQL (Neon with pgvector).

### Step 7 — Google Vertex AI (experimental, lower priority)
Google Cloud offers new accounts a $300 USD trial credit for 90 days. The abstract factory (`get_llm` in `src/agents/llm_factory.py`) already supports Vertex AI via `GOOGLE_APPLICATION_CREDENTIALS` — but the agreed Enterprise deployment target is **AWS Bedrock**, the corporate standard for private banking VPCs and effectively $0 on serverless (Step 6). So Vertex stays a lower-priority, opportunistic item to exercise with the free trial credit while it's available, not the actual deployment target.
- [ ] Exercise/validate the existing Vertex AI provider branch against real credentials while the trial credit is available.

**Small, unscheduled findings:**
- [x] `tests/integration/test_worker.py::test_worker_judge_reject` failed against real infra: it asserted `evaluate_decision` was called exactly once, but the worker's self-correction loop correctly retries up to `MAX_LLM_RETRIES` (3) on REJECT before routing to `PENDING_HUMAN_REVIEW` — the test's assertion was stale, not the worker's behavior. Discovered 2026-09-21 while running the full suite against real Postgres+RabbitMQ for the first time in a while (previously masked — this file's `db_engine` fixture needs live infra to even collect). Fixed (`fix/worker-judge-reject-retry-assertion`, commit `3b877fb`): asserts `MockJudge.call_count == settings.MAX_LLM_RETRIES` instead.

---

## Already done (not repeated above — see README.md for full detail)
- Phase 1 core engine: event-driven pipeline, MCP server, idempotency, Double Judge, Prompt Guard, self-correction loop, Supreme Court cascade judge, pessimistic locking + Recovery Sweeper.
- **Phase 1.C, fully done.** Full investigation trail: [docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md](docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md). Root cause of the real-transaction failure (`evaluate_decision()`'s unguarded `get_llm(provider="groq", ...)`) fixed (`fix/judge-groq-import-crash`) and verified against the real containerized stack: a real transaction completed cleanly end-to-end (Prompt Guard + Judge 2 both ran real Groq calls, base judges disagreed, Supreme Court cascade resolved it, `COMPLETED`). Locust re-run (100 users, 1 min): 2630 requests, 0 failures, P50 55ms, P95 87ms (down from the pre-fix baseline's P95 340ms, and flat instead of climbing over the run) — see README's System Performance table. A sample of the resulting backlog was drained through the real worker to confirm correct retry/cascade/routing behavior under real processing (no deadlocks, no stuck `PROCESSING` rows), then the rest was purged rather than fully drained, since Judge 2/Supreme Court/Prompt Guard hardcode their provider independently of `LLM_PROVIDER` and draining thousands more messages would only have burned real API quota for no additional signal. Two side findings also fixed along the way: the Gateway's per-request AMQP connection (`fix/gateway-amqp-connection-pooling`), and the `drop_all()` teardown footgun — found in *three* files, not just the one originally flagged (`test_knowledge_base_repository.py`, `test_database.py`, `test_worker.py`), all fixed the same way (`fix/integration-test-teardown-and-prompt-guard-docs`).
- **Phase 1.D, fully: RAG — common pattern, not tied to Bedrock.** `pgvector` extension + `knowledge_base` table (Alembic migration `7da4609fe11c`); `scripts/ingest_knowledge_base.py` chunks `docs/policies/refund_policy.md` and embeds it via Gemini `gemini-embedding-001` (truncated to 768 dims); the Worker runs a real cosine-similarity search (`embedding <=> claim_vector`, pgvector's `<=>` operator — not `<->`, which is L2/Euclidean distance, a mistake caught and fixed while implementing this) and injects the matched policy into the Double Judge's context, fail-open on any retrieval error. Validated end-to-end against the real Gemini API and a real Postgres. The Bedrock/Titan swap stays deferred to Step 6 (Phase 6).
- `mypy --strict` and the unit test suite are green (82% coverage across unit + integration, one pre-existing unrelated test failure noted above).
