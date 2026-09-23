# Project Context: Agentic MCP Engine

## 1. System Role and Identity

You are a Senior AI and Backend Software Engineer specializing in Distributed Systems, High-Frequency Transactional Environments, and LLMOps. You strictly adhere to SOLID principles, Clean Architecture, and Test-Driven Development (TDD). Your code must be modular, production-ready, and optimized for high concurrency.

## 2. Project Overview

Name: agentic-mcp-engine

Description: An asynchronous, fault-tolerant Agentic Workflow engine designed to process business transactions (e.g., claims, refunds) safely using Large Language Models.

Core Pattern: Event-Driven Architecture combined with the Model Context Protocol (MCP). The LLM is completely isolated from the database and business logic. It communicates exclusively through the MCP server to execute tools.

The project is organized around Phase 1 (core transactional engine, production-ready) and five infrastructure sub-phases that harden and operationalize it — Phase 1.B (MCP security boundary: authn, per-tool authz, rate limiting, audit log — see Section 5a-i; done), Phase 1.C (containerized local deployment: per-service Dockerfiles + full `docker-compose` orchestration — see Section 5a-ii; done, deployment and load validated against the real containerized stack), Phase 1.D (RAG over business rules via `pgvector` + provider-agnostic embeddings, deliberately decoupled from AWS Bedrock — see Section 5a-iii; done, validated end-to-end locally), Phase 1.E (Front-Desk / Back-Office asymmetric agentic workflow — replaces `worker.py`'s mocked primary agent with a real, server-side-revalidated one — see Section 5a-iv; designed, not yet implemented), Phase 1.F (dynamic LLM provider selection — per-request/per-judge provider override plus a hot-swappable global default, extending the existing factory pattern past a static `LLM_PROVIDER` env var — see Section 5a-v; designed, not yet implemented) — followed by Phase 2 (confidence layer: fuzzy scoring + rule-based expert system, in progress), Phase 3 (pluggable quality drift detection — EWMA default, with CUSUM, Page-Hinkley, and Kalman as selectable detectors — experimental/roadmap), Phase 4 (Ops Dashboard, done — Streamlit, see Section 5d), Phase 5 (ML Comparison Track, experimental/roadmap), and Phase 6 (cloud deployment — Google Cloud Platform primary, in progress, with Vertex AI as the inference provider; AWS secondary, roadmap — see Section 5f). See Sections 5a-5f for phase-specific directives.

## 3. Tech Stack

- API Gateway: FastAPI, Uvicorn, Pydantic (data validation).
- Message Broker: RabbitMQ, aio-pika (async task consumption).
- Database and Idempotency: PostgreSQL (with pgvector extension, Phase 1.D), SQLAlchemy (async ORM), Alembic.
- AI Core: custom async orchestration (the pipeline, retries, Double Judge, and Supreme Court cascade are hand-written — no LangChain chains/agents); LangChain (`langchain-core`) only as a thin provider-adapter layer behind `llm_factory.py`. Providers: Google GenAI (Gemini), Google Vertex AI (primary cloud provider, Phase 6 — validated end-to-end locally via ADC), Groq API, OpenAI, AWS Bedrock (secondary).
- Agent Sandbox: Model Context Protocol (MCP) Python SDK, over HTTP/SSE transport (see Section 4).
- LLMOps (Testing and Guardrails): Promptfoo (shift-left testing), Langfuse (telemetry), Asymmetric Double LLM-as-a-Judge pattern for runtime output evaluation (Gemini + GPT-OSS 20B via Groq), plus a Prompt Guard pre-execution filter and a Supreme Court cascade judge for disagreement escalation.
- Load Testing: Locust (concurrency/chaos validation, Phase 1.C).
- Containerization (Phase 1.C): Docker, Docker Compose.
- RAG Ingestion (Phase 1.D): provider-agnostic embeddings API (Gemini `gemini-embedding-001`, truncated to 768 dims, by default), `pgvector`. Cloud-native embeddings (Vertex AI on the primary GCP track, Amazon Titan on the secondary AWS track) are a Phase 6 swap, not a Phase 1.D dependency.
- Confidence Layer (Phase 2): scikit-fuzzy or a hand-rolled membership-function module for fuzzy scoring; a lightweight declarative rule engine for the Belief Rule Base (BRB).
- Observability (Phase 3, experimental): a pluggable quality-drift detector over judge/TruLens score time series — EWMA (default), CUSUM, Page-Hinkley, or a minimal Kalman filter (numpy-based, no heavy ML dependency), selected via `DRIFT_DETECTOR`.
- Frontend (Phase 4, done): Streamlit + pandas, served as its own containerized service (`docker/dashboard.Dockerfile`) — swapped in for the originally designed React/TypeScript/Vite/TanStack Query/Recharts/Tailwind stack, which was never built; a single-page, read-only internal tool doesn't need a full SPA toolchain.
- ML Comparison (Phase 5, experimental): TensorFlow, Keras, MLflow.
- Cloud Deployment (Phase 6): **primary, in progress** — Google Cloud Platform: Cloud Run, Cloud SQL for PostgreSQL (pgvector), Artifact Registry, Secret Manager, Vertex AI. **Secondary, roadmap** — AWS: API Gateway, SQS, Lambda, IAM/VPC PrivateLink, Bedrock, serverless PostgreSQL (Neon or Supabase).

## 4. Architecture Directives and Constraints

### Separation of Concerns
Never write database logic, routing logic, and AI logic in the same file. Use the following directory structure (all under `src/`, see Section 7):
- `src/api/routers/` for API routing.
- `src/core/services/` for business logic.
- `src/core/repositories/` for database access.
- `src/agents/` for LLM orchestration.
- `src/mcp_server/security/` for the Phase 1.B authn/authz/rate-limit/audit boundary.
- `src/confidence/` for the Phase 2 fuzzy layer and expert system.
- `src/observability/` for the Phase 3 pluggable drift detector.

### Idempotency is Mandatory
Every incoming request must carry a unique `request_id`. Workers MUST query the database for this ID before invoking the LLM. If the ID already exists, skip processing and return the cached result. This prevents duplicate execution in retry scenarios.

### Resilience and Retry Pattern
All external API calls (LLM endpoints, MCP tool calls) must implement exponential backoff with configurable retry limits. If the maximum retry count is exceeded, the message must be returned to RabbitMQ with a NACK so it can be requeued or sent to a dead-letter queue.

### Interface Segregation and Factory Pattern
LLM instantiation must be abstracted behind a factory. The system must switch between Gemini, Vertex AI, Groq, OpenAI, or AWS Bedrock by changing the `LLM_PROVIDER` environment variable only, without any modification to business logic. `src/agents/llm_factory.py`'s `get_llm(provider=...)` already satisfies this at the code level; Phase 1.F (Section 5a-v) extends it past a static env var to per-request/per-judge selection and a hot-swappable global default.

### Only Deterministic Code Executes Write Tools
No LLM ever calls a side-effecting MCP tool. Agents and judges propose and evaluate; the worker's deterministic code (`src/worker/refund_executor.py`) is the only caller of `execute_refund`, and only after the Double Judge approves. Every write tool must be idempotent by `request_id` (for `execute_refund`: the UNIQUE constraint on `refunds.request_id`), so a worker retry, a redelivered message, or a Recovery Sweeper requeue can never repeat a side effect.

### No Direct DB Access from the LLM Layer
The agent layer must never import or reference any SQLAlchemy model, repository, or database connection. All data access must flow through MCP tool calls.

### MCP Security Boundary is Fail-Closed (Phase 1.B)
Every MCP tool call must be authenticated before it reaches a tool: the server derives `client_id` from a bearer token, comparing only its SHA-256 hash in constant time — never from a caller-supplied header. Tool visibility and authorization are filtered by that `client_id` against a server-side allowlist; a denied or rate-limited call is rejected before tool execution, not after. Every invocation (including denied and rate-limited ones) must write an audit row (`client_id`, tool, arguments with PII masked, decision, result). If the audit write fails, the tool must not execute — the boundary fails closed, not open. Nothing in the prompt or in retrieved documents may extend a caller's tool access; that determination is made only from the authenticated identity, server-side.

### No Direct DB or MCP Access from the Confidence Layer (Phase 2)
The `confidence/` module (fuzzy layer + expert system) must be a pure function of its inputs: retrieval scores, freshness, source tier, and rule inputs passed explicitly. It must never query the database or call MCP tools directly — this keeps every rule firing reproducible and testable in isolation, which is the entire point of using it as an auditable guardrail.

### Drift Detector Runs Off the Critical Path (Phase 3)
The `observability/` module must never block or participate in the request-response cycle, regardless of which detector (`DRIFT_DETECTOR`) is active. It consumes already-persisted logs asynchronously (batch job or separate consumer), never live judge output. A failure in this module must never affect transaction processing.

### MCP Transport Protocol: HTTP/SSE (Deliberate Choice, Not `stdio`)
The worker (MCP client) and `mcp_server.py` (MCP server) communicate over **HTTP/SSE**, connecting via the `MCP_SERVER_URL` environment variable, and run as independent processes/containers.

This was an explicit choice over the MCP SDK's `stdio` transport. `stdio` requires the client to spawn the server as a child process, which would collapse the worker and the MCP server into a single process — simpler and slightly lower latency, but it removes the independent-services boundary this project is built to demonstrate (each service scales, deploys, and fails independently; the MCP server can be shared by more than one worker). If a future phase needs `stdio`'s lower overhead for a specific tool, add it as an additional transport behind the same tool interface — do not silently replace HTTP/SSE project-wide.

Known MCP SDK 2.2.0 behavior: a `tools/call` response arrives over the SSE stream, not in the POST's HTTP response. So when the Phase 1.B middleware rejects a call with a 4xx, the client never receives a response and `call_tool` waits forever. Every worker-side tool call must therefore open a fresh session per attempt with `ClientSession(read_timeout_seconds=MCP_TOOL_TIMEOUT_SECONDS)` and retry with exponential backoff, as `src/worker/refund_executor.py` does. Never reuse a session across retries.

### When Two Containers Fail to Communicate: Isolate Transport From Application
Follow [`docs/architecture/microservices_debugging_protocol.md`](docs/architecture/microservices_debugging_protocol.md) before proposing a networking/Docker-level fix for a cross-container failure. Rule of thumb: write the smallest possible script that exercises only the suspect connection (e.g. `sse_client(...)` + `.initialize()`, nothing else) and run it with `docker exec` inside the actual failing container. If it passes, the bug is in the application's control flow or exception handling around that connection, not the transport — stop suspecting Docker/DNS/networking and start reading the code path that uses the connection, especially any `async with` block wrapping a task group. The Phase 1.C MCP postmortem (`docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md`) is the canonical example: an unguarded `get_llm(provider="groq", ...)` call three layers into the application code, not a transport bug at all, despite every symptom looking like one.

### Strict Typing
Type hints are not optional. All code must pass `mypy --strict`, not just `mypy --ignore-missing-imports`. Use explicit `Optional`, `Union` (or `|`), and precise return types on every public function — no bare `Any` unless justified with an inline comment.

## 5a. Development Phases — Phase 1 (Core Engine, Sequential Execution) — COMPLETE

When asked to build Phase 1 features, follow this logical sequence (all steps below are implemented and running locally):

1. Infrastructure and Domain: Define SQLAlchemy models in `models.py` and the DB connection in `database.py`.
2. Ingestion Layer: Build FastAPI endpoints in `main.py` to validate requests via Pydantic and push them to RabbitMQ, returning HTTP 202 Accepted.
3. MCP Server: Implement `mcp_server.py` exposing isolated tools such as `get_user_history` and `execute_refund`.
4. Worker Layer: Implement `worker.py` to consume RabbitMQ messages, verify idempotency, orchestrate the LLM call, and commit the final transaction. The primary agent's proposal is still mocked (Phase 1.E replaces it); the refund execution in step 10 is real.
5. Pre-Execution Shield: A Prompt Guard model (`llama-prompt-guard-2-22m`) intercepts malicious prompts and jailbreak attempts before they reach the primary agent, failing fast.
6. Guardrails: Intercept the LLM decision with a concurrent dual-judge evaluation (Asymmetric Double LLM-as-a-Judge using Gemini and GPT-OSS 20B via Groq) before persisting the final status to PostgreSQL.
7. Self-Correction Loop: If the base judges reject on a formatting or logic error, route the feedback back to the primary agent for self-correction up to `MAX_LLM_RETRIES`.
8. Cascade Architecture (Supreme Court): If the base judges disagree or repeatedly reject, escalate to a Supreme Court Judge (Gemini 3.5 Flash) for a tie-breaking decision before falling back to `PENDING_HUMAN_REVIEW`.
9. Concurrency Control: Pessimistic row locking (`SELECT ... FOR UPDATE`) plus a `UniqueConstraint` on `request_id` prevent double-processing; a background Recovery Sweeper (`FOR UPDATE SKIP LOCKED`) reclaims and re-queues `PROCESSING` rows abandoned by a crashed worker.
10. Deterministic Execution (done, branch `feat/real-refund-execution`): after an APPROVE, `worker.py` calls the MCP `execute_refund` tool through `src/worker/refund_executor.py`, with `request_id` as the idempotency key. The tool writes to the `refunds` ledger (migration `b3e1f0c9a2d4`, `src/core/repositories/refund_repository.py`, `INSERT ... ON CONFLICT DO NOTHING`) and returns a dict whose `status` is `executed` or `already_executed`. `ClaimRequest` carries optional `order_id`, `amount`, and `currency` (`src/core/currency.py`, shared with the MCP schemas), validated at the gateway with the same limits as the MCP boundary. Outcomes:
    - Refund executed: `COMPLETED`.
    - Approved but no `order_id`/`amount`: nothing to execute, so `PENDING_HUMAN_REVIEW`.
    - Execution still failing after `MCP_TOOL_MAX_RETRIES`: `EXECUTION_FAILED`, and the message is NACKed with `requeue=False`.

    The result is stored in the trail as `judge_trail["execution"]`. `validate_fraud_score` is still a stub (fixed `0.12`).
11. Read Tools for Evidence (done, branch `feat/orders-read-tools`): an `orders` table (migration `c4d2a7e81f35`, `src/core/repositories/order_repository.py`; local sample rows via `python -m scripts.seed_orders`, never in a migration) and two read-only MCP tools on `worker-default`'s allowlist, each with a boundary argument schema: `get_order(order_id)` (`found` / `not_found`) and `get_refund_history(user_id, limit)` (count and per-currency totals over all refunds, plus the newest `limit`; joined through `orders`, since a refund's `transaction_id` is the refunded order). Not yet called by the worker: fetching them as evidence before the Double Judge, and checking the refund against the order amount deterministically, is the next increment.

## 5a-i. Development Phases — Phase 1.B (MCP Security Boundary, Done)

All five items below are implemented in `src/mcp_server/security/` (`client_registry.py`, `rate_limiter.py`, `audit.py`) and enforced by `MCPSecurityMiddleware` (`src/mcp_server/security/middleware.py`), an ASGI middleware wrapping the whole `mcp.sse_app()`. Validated: full test suite green (86/86, including `tests/unit/security/`, `tests/integration/test_rate_limiter.py`, and `tests/integration/test_mcp_server.py`'s HTTP-level 401/403/422/429 + audit-row assertions), `mypy --strict` and `ruff` clean, and smoke-tested against the real containerized stack (curl against a rebuilt `mcp_server` image, confirming the response codes and the corresponding `mcp_audit_logs` rows via `psql`). Known, accepted limitation: `tools/list` visibility isn't filtered by identity, since the SSE transport delivers that response asynchronously outside this POST-request middleware's reach — a denied client still can't *call* a non-allowlisted tool, it can just see the name. See README's Phase 1.B section for the full design writeup.

1. Authentication: each client (worker type) gets its own bearer token; the server stores only its SHA-256 hash, compares in constant time, and derives `client_id` from the token — never from a caller-supplied header.
2. Per-tool authorization: a server-side allowlist maps `client_id` to permitted tools. Tool listing is filtered by identity; calls to non-allowed tools are rejected and audited as denied.
3. Argument validation: every tool takes a Pydantic model with explicit business limits (e.g., `REFUND_MAX_AMOUNT`), a restricted currency enum, and rejection of unknown fields — enforced server-side regardless of what the LLM produced. `execute_refund` also requires a non-empty `request_id`, its idempotency key.
4. Rate limiting: per `client_id` and per tool, computed from the audit table over a sliding window (`MCP_RATE_LIMIT_PER_MIN`), so the limit holds across MCP replicas without adding Redis.
5. Audit log: every invocation (including denied and rate-limited) writes a row with timestamp, `client_id`, tool, arguments (PII masked), decision, and result. See the fail-closed directive in Section 4.

## 5a-ii. Development Phases — Phase 1.C (Containerized Local Deployment, Done — Deployment and Load Validated)

1. Dockerfiles (done): one image per service under `docker/` — `gateway.Dockerfile`, `worker.Dockerfile` (also used, via command override, for the Recovery Sweeper and a one-shot `migrate` service), `mcp_server.Dockerfile` — each installing only production dependencies as a non-root user.
2. `docker-compose.yml` (done): all eight services (`postgres`, `rabbitmq`, `migrate`, `mcp_server`, `worker`, `sweeper`, `gateway`, and — since Phase 4 — `dashboard`) orchestrated on a private `agentic_net` bridge network; the `migrate` service runs `alembic upgrade head` and gates the app services via `service_completed_successfully`.
3. Deployment validation (done): `docker compose up --build` from a clean checkout brings all containers up (seven at the time; eight since Phase 4 added `dashboard`), with the gateway and MCP server reachable across the network. Known pitfall: RabbitMQ's `-q ping` healthcheck can report healthy before the AMQP listener binds — use `check_port_connectivity` instead, and keep a bounded `restart: on-failure:N` on the app services as defense-in-depth against any other first-boot race — except the long-running consumers (`worker`, `sweeper`), which use `restart: unless-stopped` and wait for the broker themselves (`src/worker/amqp.py`'s `connect_with_retry`). HTTP reachability is not the same as a working transaction: a real Worker→MCP-server session failed on nearly every transaction. Root cause identified (not a transport issue): `src/agents/judge.py`'s `evaluate_decision()` calls `get_llm(provider="groq", ...)` with no guard; `langchain-groq` is undeclared, so it `ImportError`s inside the MCP session's `async with` block, which anyio's `TaskGroup` reports as a generic transport failure. See [`docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md`](docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md) for the full diagnosis and the [Microservices Debugging Protocol](docs/architecture/microservices_debugging_protocol.md) for the general practice that found it — isolate the transport plane from the application plane before suspecting Docker networking. Fixed (`fix/judge-groq-import-crash`, commit `79179f9`): `langchain-groq` is now declared, and `_run_single_judge()` constructs its LLM inside its existing `try`/`except` so a construction failure fails that judge closed to `REJECT` instead of raising out of `evaluate_decision()` — see the postmortem's "Resolution" section. Verified for real after a `docker compose build --no-cache` rebuild: a real transaction completed cleanly end-to-end (`COMPLETED`, no `TaskGroup`/`RemoteProtocolError`).
4. Load validation (done): Locust (100 users, spawn rate 10, 1 minute) against the containerized stack: 2630 requests, 0 failures, P50 55ms, P95 87ms — down from a pre-fix baseline of P95 340ms, and flat instead of climbing over the run. A sample of the resulting backlog was drained through the real worker to confirm correct retry/Supreme-Court-cascade/routing behavior under real processing, with no deadlocks; the remainder was purged rather than fully drained, since Judge 2/Supreme Court/Prompt Guard hardcode their provider independently of `LLM_PROVIDER`. See README's System Performance & Telemetry table for the full numbers.
5. Chaos/idempotency validation (done, branch `test/chaos-idempotency`): `tests/performance/chaos_idempotency.py` against the stack with `docker-compose.chaos.yml` (every LLM role on `mock`, MCP rate limit lifted, sweeper every 10s): 2,000 claims (1,800 unique, 10% duplicates), worker `docker kill`ed twice and RabbitMQ restarted once while draining, then invariants checked in SQL. It found two real bugs:
    - **Lost messages:** the gateway published transient messages into the durable queue, so a broker restart dropped every queued claim that already had its 202 (first run: 985 of 1,800 lost). Fixed: `delivery_mode=PERSISTENT` in `src/api/main.py`, plus a fixed `hostname: rabbitmq` in compose so a recreated broker container finds its data.
    - **Worker crash on broker restart:** `ack()` on the closed channel raised, the handler's `nack()` raised again, and the process died; its first reconnect failed while the broker was down, so only Docker's bounded restart brought it back. Fixed: `src/worker/amqp.py` (`safe_ack`/`safe_nack` log and move on — the broker redelivers and idempotency absorbs it — and `connect_with_retry`), `handle_delivery()` in `worker.py`.

    Result after both fixes: 1,800/1,800 `COMPLETED`, 0 double refunds, 0 lost, nothing stuck in `PROCESSING`; the worker survived the broker restart without a restart; the second kill landed between `execute_refund` and the final commit, and the sweeper's requeue came back `already_executed` with the same `refund_id`.
6. Processing throughput (done, branch `perf/processing-throughput`): `tests/performance/processing_throughput.py --prefill` (workers `docker pause`d while 1,000 claims are queued, then unpaused, so the drain rate is the pool's and not the gateway's) against the chaos override plus `docker-compose.scale.yml` (drops the worker's fixed `container_name` so `--scale worker=N` works). Median claims/s on a 4-core laptop, LLMs mocked: 1 worker 9.2, 2 → 13.8, 4 → 17.4, 8 → 19.6. It flattens because the laptop's CPU saturates (per claim: ~59 ms of CPU in the worker, ~29 ms in the single MCP server process, which caps that process near 34/s). It found and fixed two measurement-distorting bugs:
    - **`updated_at` stamped too early:** `onupdate=func.now()` is the start of the enclosing transaction, which the worker holds open from retrieval through the judges and the refund, so `created_at` → `updated_at` (and the dashboard's latency) missed that time. Now `func.clock_timestamp()` (ORM-side, no migration).
    - **RabbitMQ healthcheck kept the idle broker at up to ~150% CPU:** each `rabbitmq-diagnostics` run boots an Erlang VM for ~5s, and the interval was 5s. Now `start_interval: 2s` during boot and `interval: 60s` after (it only gates first boot).

    Don't measure scaling with `docker stop`/`start`: a restarted worker re-imports LangChain inside the measured window. Pause instead.

## 5a-iii. Development Phases — Phase 1.D (RAG over Business Rules, Done)

RAG is a pattern (embed → store → similarity search → inject into the prompt); AWS Bedrock is a provider. This phase deliberately does not depend on Bedrock — it targets infrastructure already running locally, so it was validated without first configuring AWS IAM/Bedrock access. Migrating the embeddings call to a cloud-native provider (Vertex AI on GCP, or Amazon Titan on AWS) is Phase 6's job (see Section 5f), not this phase's.

1. Enable `pgvector` + `knowledge_base` table (done, migration `7da4609fe11c`): activates the extension and adds a `knowledge_base` table (`content`, `source`, `source_tier`, `embedding vector(768)`, timestamps) — the `source_tier`/timestamp columns exist specifically to feed Phase 2's fuzzy layer later.
2. Embeddings module (done, `scripts/ingest_knowledge_base.py` + `src/core/services/chunking.py`): vectorizes `docs/policies/refund_policy.md` using `src/agents/llm_factory.py`'s `get_embeddings()` — default Gemini `gemini-embedding-001`, truncated from its native 3072 dims to 768 via `output_dimensionality` — and inserts the chunks into `knowledge_base`. Do not hard-code AWS Bedrock/Titan here.
3. Dynamic context injection (done, `src/worker/worker.py` + `src/core/services/retrieval_service.py`): before the Double Judge call — regardless of `LLM_PROVIDER` — the Worker runs a cosine-similarity search (`KnowledgeBase.embedding.cosine_distance(vector)`, i.e. pgvector's `<=>` operator — not `<->`, which is L2/Euclidean distance and was caught as a mislabel while building this) over `knowledge_base` and injects the matched policy text into `evaluate_decision`'s `context`. Not gated on `LLM_PROVIDER=bedrock`. Fails open on any retrieval error (embeddings API down, DB error) — never blocks transaction processing, mirroring `prompt_guard.py`'s fail-open pattern.
4. This phase feeds the Phase 2 fuzzy layer's inputs (similarity score, freshness, source tier) once both are implemented — do not build Phase 2 scoring logic that assumes retrieval exists before this phase ships it.

## 5a-iv. Development Phases — Phase 1.E (Front-Desk / Back-Office Asymmetric Agentic Workflow, Designed, not yet implemented)

Phase 1 step 4 ("Worker Layer") was always scoped to orchestrate a real primary-agent LLM call, but `worker.py` has only ever hardcoded it (`mock_primary_action = "execute_refund"`, `mock_primary_args = body`). This phase replaces that mock with a real one, and in doing so extends Phase 1.B's "never trust LLM output, validate server-side" doctrine to a new input surface — the primary agent's own proposed intent, not just MCP tool arguments.

1. **The Front-Desk (probabilistic UX):** a conversational LLM that acts purely as an interface — it contains the user and translates unstructured text into a standardized JSON payload. It holds minimal privilege: no access to the database, the RAG table, or the MCP server. It never decides an outcome, only proposes a structured intent. If it cannot map the user's message to a valid payload, it asks a clarifying question rather than guessing a field.
2. **The Back-Office (deterministic execution):** the existing isolated async orchestrator (FastAPI + RabbitMQ + `worker.py`). It never trusts the Front-Desk's JSON at face value — every field is re-validated server-side against a strict Pydantic schema (the same "argument validation enforced server-side regardless of what the LLM produced" rule from Section 5a-i applies here, since the Front-Desk's output is functionally untrusted input). Once validated, it applies cross-checked evaluation (Double Judge), retrieves corporate policy context (pgvector, Phase 1.D), and resolves the request through hard deterministic rules (Belief Rule Base, Phase 2) and the MCP server.
3. **The Feedback Loop:** the Back-Office exposes an auditable, objective verdict (e.g. `REJECTED: <objective reason>`, never a raw judge rationale that could leak internal reasoning or business logic) and the Front-Desk only reads that state to phrase a human-readable response — it never re-interprets or overrides the verdict.
4. Dependency order: does not require Phase 2 to be complete first — the mocked path already flows through the Double Judge today regardless of what proposes the action — but pairs naturally with Phase 2 once both are real, since a rule base evaluating real, varied Front-Desk intents is more meaningful than one hardcoded action.

## 5a-v. Development Phases — Phase 1.F (Dynamic LLM Provider Selection, Designed, not yet implemented)

`src/agents/llm_factory.py`'s `get_llm(provider=...)` already implements the Factory pattern Section 4 promises. First slice done (branch `feat/mock-provider-all-roles`): the role → provider pairing (Judge 1 and the Supreme Court tie-break on `"gemini"`, Judge 2 and the Prompt Guard on `"groq"`) lives in one place, `src/agents/provider_roles.py`'s `provider_for_role()`, and `LLM_PROVIDER=mock` routes every role to the mock (no paid calls in local or load-test runs). Any other `LLM_PROVIDER` value keeps that fixed pairing, so the only lever is still the global env var, which requires editing `.env` and restarting containers, and can't mix providers per judge role or per request — the rest of this phase closes that gap.

Two complementary, non-exclusive levers — which to build first is an implementation-time decision, not committed here:

1. **Per-request override (demo-friendly):** `ClaimRequest` gains optional `judge_1_provider`/`judge_2_provider` fields, validated against the same provider allowlist `get_llm()` already supports (`gemini`, `groq`, `openai`, `vertex`, `bedrock`, `mock`) — an invalid value is rejected at the Pydantic layer, the same server-side-revalidation doctrine as Phase 1.B/1.E. The Streamlit dashboard's ingestion panel (`src/ui/app.py`) gets two `st.selectbox` dropdowns. `judge.py`'s `evaluate_decision()` accepts explicit providers instead of hardcoding `"gemini"`/`"groq"`, falling back to today's hardcoded pairing when a caller doesn't specify one — so existing behavior doesn't change unless a caller opts in.
2. **Global hot-swappable default (operational):** an admin surface (e.g. `PUT /config/providers`) backed by `pydantic-settings` and/or a config table that updates the active default provider(s) in memory or the database — a "vendor is down, reroute now" lever without a container restart or `.env` edit.

Scope:
1. Extend `ClaimRequest`/the claims ingestion path with the optional per-judge provider fields (item 1 above).
2. Thread the chosen provider through `worker.py` → `evaluate_decision()` → `_run_single_judge()`, as an override on top of `provider_for_role()`.
3. Add the two provider dropdowns to the dashboard's ingestion panel.
4. The global admin-config lever (item 2 above) is a separate, later increment — not required to ship items 1-3.
5. Does not touch the MCP tool-call provider boundary (Phase 1.B's allowlist/validation) — this is about which LLM answers a judge/agent call, not about tool authorization.

## 5b. Development Phases — Phase 2 (Confidence Layer)

1. Fuzzy Layer: Implement `confidence/fuzzy_layer.py`. Input: raw pgvector similarity score, document freshness (days since last update), source authority tier (enum). Output: a graded membership (low/medium/high) per signal, plus a combined confidence score. No hard thresholds — every cutoff must be expressed as a membership function, not an `if score > X`.
2. Rule Base: Implement `confidence/rule_base.py` and declarative rule files under `confidence/rules/`. Rules apply belief degrees, not booleans. Start with the two highest-risk tools only: `execute_refund` and `validate_fraud_score`.
3. Integration Point: The rule base output is a second, independent signal alongside the Phase 1 LLM-judge verdict. A transaction auto-approves only if both agree above their respective thresholds (`EXPERT_SYSTEM_CONFIDENCE_THRESHOLD` for the rule base). Disagreement routes to `PENDING_HUMAN_REVIEW`, same as a judge REJECT.
4. Every rule firing must log: rule id, inputs, belief degree, and the final verdict — this log is what makes the layer auditable; do not skip it to save write volume.

## 5c. Development Phases — Phase 3 (Quality Drift Detection, Experimental)

The detector is pluggable via `DRIFT_DETECTOR`, over the time series of judge/TruLens scores already logged by Phase 1. Parsimony rule: implement the simplest detector that solves the problem in front of you; reach for a heavier one only when evidence shows the simpler one fails.

1. `EWMA` (default): one smoothing parameter (`EWMA_LAMBDA`), no state-space model — detects gradual drift.
2. `CUSUM` / `Page-Hinkley`: better suited to abrupt step changes (a prompt deploy, a model or provider switch).
3. `kalman_monitor.py` (optional): a simple 1D (or low-dimensional) Kalman filter with exactly two tunable parameters — process noise and measurement noise. Assumes a linear-Gaussian state and measurement model; quality scores are bounded in [0, 1] and often skewed, so check that assumption against real data before relying on it.
4. `observability/alerting.py`: fires only when the active detector's estimate exits its control band (`DRIFT_ALERT_SIGMA` standard deviations), not on individual outlier scores.
5. This phase is design/prototype status. Do not wire it into the transactional critical path under any circumstance — see the constraint in Section 4. Do not add a trained drift classifier — it would need its own training data and become another opaque component to monitor.

## 5d. Development Phases — Phase 4 (Ops Dashboard, Done)

1. Scope: A read-only Streamlit dashboard (`src/ui/app.py`) — health strip, ingestion panel, transaction monitor with a per-row decision-inspector expander (Judge 1/Judge 2/Supreme Court trail; a Phase 2 belief-rule-base panel that is a static placeholder until Phase 2 ships). Quality Trend is deferred — it needs Phase 3's drift-detector output, which doesn't exist yet.
2. Architecture Constraint: The UI must act as an external consumer. It fetches data exclusively from new read-only (GET) endpoints under `api/routers/` (`transactions.py`, `system.py`) via `src/ui/api_client.py`. It must never connect directly to the database, the MCP server, or the confidence/observability modules — even the MCP health check is done server-side by `system_health_service.py`, treating a bare 401 from the Phase 1.B security boundary as proof of life.
3. Prerequisite persisted for this phase: Judge 1/Judge 2/Supreme Court verdicts were previously only logged, never queryable. Migration `622b710f2855` added `transactions.created_at` and `transactions.judge_trail` (JSONB); `src/agents/judge.py`'s `evaluate_decision()` now returns a `"trail"` key that `worker.py` persists after each decision.

## 5e. Development Phases — Phase 5 (ML Comparison Track, Experimental)

1. Scope: An offline TensorFlow/Keras MLP trained on the Phase 2 rule base inputs (`validate_fraud_score` features) to compare its accuracy against the deterministic expert system.
2. Tooling: All training runs and resulting models must be versioned and tracked using MLflow.
3. Architecture Constraint: The MLP is strictly out-of-band. It never participates in the live transaction approval path. Its output is logged solely for offline comparison against the rule base verdicts.

## 5f. Development Phases — Phase 6 (Cloud Deployment: Google Cloud Primary, In Progress; AWS Secondary)

Decision (2026-09-22): Google Cloud Platform is the primary deployment target and Vertex AI the primary cloud inference provider; AWS is a secondary target. Rationale: the stack already runs on the Gemini model family (Judge 1, Supreme Court, `gemini-embedding-001`), so Vertex AI gives the same models with service-account auth and in-project governance, and the Phase 1.C containers map almost 1:1 onto Cloud Run. Dependencies (Phase 1.C containerization, Phase 1.D provider-agnostic embeddings) are both complete.

**Primary — Google Cloud (in progress):**
1. Vertex AI provider (done, branch `feat/vertex-provider`): runs through `langchain-google-genai`'s Vertex mode (`vertexai=True`; `langchain-google-vertexai`'s `ChatVertexAI` is deprecated and not a dependency). `get_llm("vertex")` and `get_embeddings("vertex")` read `VERTEX_MODEL`/`VERTEX_EMBEDDING_MODEL`/`VERTEX_PROJECT` and authenticate via ADC (no API key). Two locations: chat on `VERTEX_LOCATION=global` (the Gemini 3.5 models 404 on regional endpoints), embeddings on `VERTEX_EMBEDDING_LOCATION=us-central1` (~1 s vs ~12 s on `global`). Embeddings stay at 768 dims and are identical to AI Studio's (cosine 1.0), so the existing `knowledge_base` rows need no re-ingestion. `LLM_PROVIDER=vertex` moves the Gemini roles (Judge 1, Supreme Court) to Vertex; Judge 2 and the Prompt Guard stay on Groq. Locally, `docker-compose.gcp.yml` mounts the host ADC file read-only into the worker only. Validated with real claims through the containerized stack: happy path `COMPLETED` in 6.6 s, and an escalation where the Supreme Court on Vertex broke a Judge 1/Judge 2 split. Changing providers must stay behind the factory (Section 4) — no business-logic changes.
2. Artifact Registry: push the existing `docker/*.Dockerfile` images (gateway, worker, mcp_server, dashboard).
3. Cloud Run: gateway, MCP server, dashboard as HTTP services; worker and Recovery Sweeper as min-instance consumers. Keep the worker and MCP server as separate services over HTTP/SSE (Section 4) — do not collapse them.
4. Cloud SQL for PostgreSQL with `pgvector`; Alembic runs as a one-shot job, mirroring the local `migrate` service. Section 8's migration-confirmation rule applies to the cloud database too.
5. Secret Manager for MCP client tokens and provider keys; Cloud Run-managed TLS.
6. Messaging: open decision — self-hosted RabbitMQ (ACK/NACK contract unchanged) vs. Pub/Sub (idempotency/retry contract must be re-validated first). Do not switch brokers without confirming with the user.
7. Re-test of load: repeat the Phase 1.C Locust validation against Cloud Run and compare against the local baseline.
8. Model Garden and cost benchmark (next branch, `feat/vertex-model-garden`, not started): Claude on Vertex (`claude-sonnet-5`, `claude-haiku-4-5`) as candidate judges through the official `anthropic[vertex]` SDK (`AnthropicVertex`, ADC) behind the factory; a verdict-stability check (the same claims N times per model — `claude-sonnet-5` rejects `temperature` with a 400 and the Gemini 3.5 models are thinking models, so determinism is measured, not assumed from `temperature=0`); and `scripts/cost_benchmark.py`, which runs the same claim set through each candidate and prints a Markdown table of latency, tokens, and cost at prices fetched on the run date. The asymmetric-judge rule (Section 10) still applies: Judge 1 and Judge 2 must come from different model families.

**Secondary — AWS (roadmap):**
1. IAM and Bedrock: least-privilege IAM policies scoped to the foundation models actually invoked, plus VPC PrivateLink endpoints so inference traffic stays in the VPC.
2. Embeddings provider swap: Amazon Titan Embeddings via Bedrock behind the same `get_embeddings()` interface — deliberately not in Phase 1.D itself (Section 5a-iii).
3. Serverless topology: FastAPI Gateway → API Gateway, RabbitMQ → SQS, Worker → Lambda, with a serverless PostgreSQL provider (Neon or Supabase) with `pgvector`.

## 6. Coding Standards and Non-Negotiable Rules

- Python version: 3.11 or higher.
- All functions that perform I/O must be async.
- All public functions and classes must have type annotations and docstrings.
- Configuration must be loaded from environment variables via `pydantic-settings`. Never hardcode secrets or connection strings.
- Every module must have a corresponding test file under `tests/`. Use `pytest` and `pytest-asyncio`.
- Use `structlog` for structured JSON logging. Never use `print()`.
- Follow PEP 8. Line length limit is 100 characters.
- Do not mix concerns: one responsibility per file, one responsibility per function.
- Do not use blocking I/O inside an `async` function (`time.sleep`, `requests.get`). Use `asyncio.sleep`, `httpx.AsyncClient`, or the async driver already in use (`aio-pika`, `asyncpg`).
- Do not use `from module import *`. Always use explicit imports.
- Do not catch `Exception` as a bare catch-all without re-raising or logging the specific error.
- Do not leave `TODO` comments in code. Either implement the feature or explicitly ask the user to decide.
- Do not put an HTTP client call (`httpx`, `requests`) inside `src/core/repositories/` — repositories are for database access only; external calls belong in `src/core/services/` or `src/agents/`.

## 6b. Test-Driven Development Workflow (Mandatory)

This project follows strict Red-Green-Refactor TDD. Do not write production code before a failing test exists for it.

1. **Red**: Given a new function, endpoint, tool, rule, or estimator step, write the test first, in the matching `tests/unit/` or `tests/integration/` path. Run it and confirm it fails (there is nothing to pass yet, or it fails for the right reason).
2. **Green**: Write the minimum implementation needed to make that test pass. Do not add unrequested functionality at this step.
3. **Refactor**: With the test passing, clean up naming, structure, and duplication. Re-run the test after every change to confirm it still passes.

Rules that apply this workflow project-wide:
- Never present a new function or endpoint as done without also presenting its test.
- If asked to fix a bug, first write a test that reproduces the bug (it must fail), then fix the code until it passes.
- For Phase 2 rule base entries, "the test" is a fixed input → expected belief-degree/verdict pair. Add it before adding the rule.
- For the Phase 3 drift detector (whichever is active via `DRIFT_DETECTOR`), tests use synthetic score sequences (known noise + known drift point) to assert the detector flags the drift within a bounded number of steps — do not skip this because it's "just observability."

## 7. File and Directory Layout (The `src/` Pattern)

To avoid `PYTHONPATH`/`ModuleNotFoundError` issues and keep module boundaries strict, all application code lives inside `src/`. This makes every internal import absolute (`from src.core import database`, `from src.confidence import fuzzy_layer`) instead of relying on the working directory, and it is what makes the same import paths work identically locally, in tests, and inside Docker.

```
agentic-mcp-engine/
    src/
        api/                 # FastAPI entrypoints (formerly 'app')
            routers/
            main.py
        core/                # Shared domain logic
            config.py
            currency.py      # Currency enum shared by the gateway and the MCP tools
            database.py
            models.py
            services/
            repositories/
        agents/              # LLM orchestration and provider factory
        mcp_server/          # Tool registry and MCP endpoints (HTTP/SSE)
            mcp_server.py
            tools/
            security/        # Phase 1.B: authn, authz, rate limiting, audit
        worker/              # RabbitMQ consumer, MCP client
            worker.py
            recovery_sweeper.py
            refund_executor.py  # deterministic execute_refund caller (retries, timeouts)
            amqp.py          # safe ack/nack and broker-wait for the consumers (chaos-test fixes)
        ui/                  # Phase 4: Streamlit Ops Dashboard (done)
            app.py
            api_client.py    # the dashboard's ONLY data source (gateway HTTP API)
            stats.py
            theme.py
            config.py
        confidence/          # Phase 2: fuzzy layer & expert system
            fuzzy_layer.py
            rule_base.py
            rules/
        observability/       # Phase 3: pluggable drift detector (experimental)
            detectors/       # EWMA, CUSUM, Page-Hinkley, Kalman
            alerting.py
    tests/
        unit/
            confidence/
            observability/
            security/
        integration/
        performance/         # Locust load/chaos suite (Phase 1.C)
    alembic/
    alembic.ini
    .env.example
    pyproject.toml
    docker-compose.yml
    Dockerfile
```

## 8. Safety and Review Boundaries

Before writing or modifying any file that touches the following areas, pause and confirm intent with the user:

- Any file in `repositories/` that runs DELETE or UPDATE statements without a WHERE clause.
- Any change to Alembic migration files that drops a column or table.
- Any modification to the `worker.py` ACK/NACK logic.
- Any change to `mcp_server.py` that removes or renames an existing tool, as this is a breaking change for live agents.
- Any change to a rule in `confidence/rules/` that lowers a belief-degree threshold for `execute_refund` or `validate_fraud_score` (this weakens a financial safety gate).
- Any change to `.env` files or secrets.
- `PENDING.md` must never be deleted or emptied, by any means (`rm`, `Remove-Item`, `git rm`, shell redirection, `git clean`, etc.) — it is the user's personal working roadmap. Enforced as a hard `deny` in `.claude/hooks/safety_guard.py`, not just an `ask`. Editing its content is fine; removing the file or its content is not.
- Before running an Alembic upgrade/downgrade command, confirm the current revision (`alembic current`) and the target revision with the user.
- Before deleting or moving a file that defines database models, router registrations, or MCP tool registrations, list what will be affected and ask for confirmation.

When refusing an action under this section, always state the correct alternative in the same reply — don't just decline.

## 9. Environment Variables Reference

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `TEST_DATABASE_URL` | Test suite only: database pytest runs against (default: `DATABASE_URL`'s database name + `_test`, same server). Must end in `_test` — the suite refuses to start otherwise, so tests never truncate the dev DB |
| `RABBITMQ_URL` | RabbitMQ AMQP connection string |
| `LLM_PROVIDER` | Active LLM provider: `gemini`, `vertex`, `groq`, `openai`, `bedrock`, or `mock` |
| `OPENAI_API_KEY` | OpenAI API key (when LLM_PROVIDER=openai) |
| `GEMINI_API_KEY` | Google GenAI API key |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCP credentials for Vertex AI when running outside GCP (on Cloud Run, the attached service account / ADC is used instead) |
| `VERTEX_PROJECT` | Phase 6: GCP project for Vertex AI (empty: the project ADC resolves) |
| `VERTEX_LOCATION` | Phase 6: Vertex AI location (default: `global`; the Gemini 3.5 models aren't served from regional endpoints) |
| `VERTEX_EMBEDDING_LOCATION` | Phase 6: Vertex location for embeddings (default: `us-central1`; ~1 s per embedding vs ~12 s on `global`, measured locally) |
| `VERTEX_MODEL` | Phase 6: Vertex chat model for the Gemini roles (default: `gemini-3.5-flash-lite`) |
| `VERTEX_EMBEDDING_MODEL` | Phase 6: Vertex embeddings model, requested at 768 dims (default: `gemini-embedding-001`) |
| `GROQ_API_KEY` | Groq API key |
| `AWS_ACCESS_KEY_ID` | AWS key (when LLM_PROVIDER=bedrock) |
| `AWS_SECRET_ACCESS_KEY` | AWS secret (when LLM_PROVIDER=bedrock) |
| `LANGFUSE_SECRET_KEY` | Langfuse telemetry secret |
| `LANGFUSE_PUBLIC_KEY` | Langfuse telemetry public key |
| `PROMPT_GUARD_THRESHOLD` | Prompt Guard malicious-probability score (Groq returns a float in [0, 1], not a label) at or above which a claim is blocked (default: 0.5) |
| `MCP_SERVER_URL` | URL of the running MCP server |
| `GATEWAY_URL` | Phase 4, dashboard side: base URL of the gateway API the Streamlit dashboard consumes (default: `http://localhost:8000`) |
| `MAX_LLM_RETRIES` | Maximum retry count for LLM calls (default: 3) |
| `IDEMPOTENCY_TTL_SECONDS` | TTL for idempotency record cache (default: 86400) |
| `MCP_CLIENTS_FILE` | Phase 1.B, server side: path to the client registry (`client_id`, token hash, allowed tools) |
| `MCP_CLIENT_TOKEN` | Phase 1.B, worker side: this worker's bearer token for the MCP server |
| `MCP_RATE_LIMIT_PER_MIN` | Phase 1.B: default calls per minute per client and tool (default: 30) |
| `REFUND_MAX_AMOUNT` | Phase 1.B: upper bound enforced by `execute_refund` validation (default: 10000) |
| `MCP_TOOL_TIMEOUT_SECONDS` | Worker side: read timeout per MCP tool-call attempt; bounds the MCP SDK's hang when the security boundary rejects a call with a 4xx (default: 10) |
| `MCP_TOOL_MAX_RETRIES` | Worker side: attempts at `execute_refund` before the transaction is marked `EXECUTION_FAILED` (default: 3) |
| `MCP_TOOL_BACKOFF_BASE_SECONDS` | Worker side: base delay of the exponential backoff between tool-call attempts (default: 1.0) |
| `EXPERT_SYSTEM_CONFIDENCE_THRESHOLD` | Phase 2: minimum belief degree required for rule-base auto-approval (default: 0.85) |
| `DRIFT_DETECTOR` | Phase 3: active detector — `ewma`, `cusum`, `page_hinkley`, or `kalman` (default: `ewma`) |
| `EWMA_LAMBDA` | Phase 3: EWMA smoothing factor (default: 0.2) |
| `DRIFT_ALERT_SIGMA` | Phase 3: control-limit width in standard deviations that triggers a drift alert (default: 3.0) |

## 10. Asymmetric Double LLM-as-a-Judge Guardrail Contract

Every LLM decision must pass through the concurrent Double Judge (Gemini + GPT-OSS 20B via Groq, `openai/gpt-oss-20b`) before being committed. Both judges evaluate:
- Was the action within the agent's authorized scope?
- Is the output well-formed and parseable?
- Does the decision contradict any business rule (e.g., refund exceeds the original transaction amount)?

If EITHER judge rejects on a formatting or logic error, the feedback is routed back to the primary agent for self-correction, up to `MAX_LLM_RETRIES` (see Section 5a, step 7). If the judges disagree or continue to reject after retries are exhausted, the transaction escalates to a Supreme Court cascade judge for a tie-breaking decision (Section 5a, step 8) before falling back to `PENDING_HUMAN_REVIEW` with a human-readable reason logged.

For `execute_refund` and `validate_fraud_score` specifically (Phase 2 active), the Double Judge verdict (requiring APPROVE from both, after any self-correction/cascade resolution above) and the expert-system verdict are both required before auto-approval. Either one alone routes to `PENDING_HUMAN_REVIEW`.

## 11. Git and Branching Conventions

- **Branching model**: GitHub Flow (single long-lived `main`, short-lived feature branches, no permanent `development` branch). `main` must always be deployable.
- **Branch naming**: `feat/<short-description>`, `fix/<short-description>`, `chore/<short-description>` (e.g., `feat/fuzzy-scoring-layer`).
- **Commit messages**: Conventional Commits format — `type(scope): description` (e.g., `feat(confidence): add fuzzy membership functions for retrieval scoring`).
- **Workflow**: branch from `main` → commit incrementally following the TDD cycle in Section 6b → open a PR to `main` even when working solo, so CI (lint, type-check, unit tests) runs before merge → squash-merge → delete the branch.
- **Before opening a PR**: `ruff check`, `mypy`, and `pytest tests/unit/` must all pass locally.
- Do not commit directly to `main`.