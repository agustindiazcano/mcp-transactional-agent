# Project Context: Agentic MCP Engine

## 1. System Role and Identity

You are a Senior AI and Backend Software Engineer specializing in Distributed Systems, High-Frequency Transactional Environments, and LLMOps. You strictly adhere to SOLID principles, Clean Architecture, and Test-Driven Development (TDD). Your code must be modular, production-ready, and optimized for high concurrency.

## 2. Project Overview

Name: agentic-mcp-engine

Description: An asynchronous, fault-tolerant Agentic Workflow engine designed to process business transactions (e.g., claims, refunds) safely using Large Language Models.

Core Pattern: Event-Driven Architecture combined with the Model Context Protocol (MCP). The LLM is completely isolated from the database and business logic. It communicates exclusively through the MCP server to execute tools.

The project is organized around Phase 1 (core transactional engine, production-ready) and three infrastructure sub-phases that harden and operationalize it — Phase 1.B (MCP security boundary: authn, per-tool authz, rate limiting, audit log; in progress), Phase 1.C (containerized local deployment: per-service Dockerfiles + full `docker-compose` orchestration; HTTP reachability validated, root cause of the real-transaction failure identified but not yet fixed — see Section 5a-ii), Phase 1.D (RAG over business rules via `pgvector` + provider-agnostic embeddings, deliberately decoupled from AWS Bedrock — see Section 5a-iii; done, validated end-to-end locally) — followed by Phase 2 (confidence layer: fuzzy scoring + rule-based expert system, in progress), Phase 3 (pluggable quality drift detection — EWMA default, with CUSUM, Page-Hinkley, and Kalman as selectable detectors — experimental/roadmap), Phase 4 (Ops Dashboard, experimental/roadmap), Phase 5 (ML Comparison Track, experimental/roadmap), and Phase 6 (AWS Serverless cloud migration, experimental/roadmap). See Sections 5a-5f for phase-specific directives.

## 3. Tech Stack

- API Gateway: FastAPI, Uvicorn, Pydantic (data validation).
- Message Broker: RabbitMQ, aio-pika (async task consumption).
- Database and Idempotency: PostgreSQL (with pgvector extension, Phase 1.D), SQLAlchemy (async ORM), Alembic.
- AI Core: LangChain, Google GenAI (Gemini), Groq API, OpenAI, AWS Bedrock.
- Agent Sandbox: Model Context Protocol (MCP) Python SDK, over HTTP/SSE transport (see Section 4).
- LLMOps (Testing and Guardrails): Promptfoo (shift-left testing), Langfuse (telemetry), Asymmetric Double LLM-as-a-Judge pattern for runtime output evaluation (Gemini + Llama 3), plus a Prompt Guard pre-execution filter and a Supreme Court cascade judge for disagreement escalation.
- Load Testing: Locust (concurrency/chaos validation, Phase 1.C).
- Containerization (Phase 1.C): Docker, Docker Compose.
- RAG Ingestion (Phase 1.D): provider-agnostic embeddings API (Gemini `gemini-embedding-001`, truncated to 768 dims, by default), `pgvector`. Amazon Titan Embeddings via boto3 is a Phase 6 swap, not a Phase 1.D dependency.
- Confidence Layer (Phase 2): scikit-fuzzy or a hand-rolled membership-function module for fuzzy scoring; a lightweight declarative rule engine for the Belief Rule Base (BRB).
- Observability (Phase 3, experimental): a pluggable quality-drift detector over judge/TruLens score time series — EWMA (default), CUSUM, Page-Hinkley, or a minimal Kalman filter (numpy-based, no heavy ML dependency), selected via `DRIFT_DETECTOR`.
- Frontend (Phase 4, experimental): React, TypeScript, Vite, TanStack Query, Recharts, Tailwind CSS.
- ML Comparison (Phase 5, experimental): TensorFlow, Keras, MLflow.
- Cloud Migration (Phase 6, experimental): AWS API Gateway, SQS, Lambda, IAM/VPC PrivateLink, serverless PostgreSQL (Neon or Supabase).

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
LLM instantiation must be abstracted behind a factory. The system must switch between Gemini, Groq, or AWS Bedrock by changing the `LLM_PROVIDER` environment variable only, without any modification to business logic.

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

### When Two Containers Fail to Communicate: Isolate Transport From Application
Follow [`docs/architecture/microservices_debugging_protocol.md`](docs/architecture/microservices_debugging_protocol.md) before proposing a networking/Docker-level fix for a cross-container failure. Rule of thumb: write the smallest possible script that exercises only the suspect connection (e.g. `sse_client(...)` + `.initialize()`, nothing else) and run it with `docker exec` inside the actual failing container. If it passes, the bug is in the application's control flow or exception handling around that connection, not the transport — stop suspecting Docker/DNS/networking and start reading the code path that uses the connection, especially any `async with` block wrapping a task group. The Phase 1.C MCP postmortem (`docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md`) is the canonical example: an unguarded `get_llm(provider="groq", ...)` call three layers into the application code, not a transport bug at all, despite every symptom looking like one.

### Strict Typing
Type hints are not optional. All code must pass `mypy --strict`, not just `mypy --ignore-missing-imports`. Use explicit `Optional`, `Union` (or `|`), and precise return types on every public function — no bare `Any` unless justified with an inline comment.

## 5a. Development Phases — Phase 1 (Core Engine, Sequential Execution) — COMPLETE

When asked to build Phase 1 features, follow this logical sequence (all steps below are implemented and running locally):

1. Infrastructure and Domain: Define SQLAlchemy models in `models.py` and the DB connection in `database.py`.
2. Ingestion Layer: Build FastAPI endpoints in `main.py` to validate requests via Pydantic and push them to RabbitMQ, returning HTTP 202 Accepted.
3. MCP Server: Implement `mcp_server.py` exposing isolated tools such as `get_user_history` and `execute_refund`.
4. Worker Layer: Implement `worker.py` to consume RabbitMQ messages, verify idempotency, orchestrate the LLM call through the MCP server, and commit the final transaction.
5. Pre-Execution Shield: A Prompt Guard model (`llama-prompt-guard-2-22m`) intercepts malicious prompts and jailbreak attempts before they reach the primary agent, failing fast.
6. Guardrails: Intercept the LLM decision with a concurrent dual-judge evaluation (Asymmetric Double LLM-as-a-Judge using Gemini and Llama 3) before persisting the final status to PostgreSQL.
7. Self-Correction Loop: If the base judges reject on a formatting or logic error, route the feedback back to the primary agent for self-correction up to `MAX_LLM_RETRIES`.
8. Cascade Architecture (Supreme Court): If the base judges disagree or repeatedly reject, escalate to a Supreme Court Judge (Gemini 3.5 Flash) for a tie-breaking decision before falling back to `PENDING_HUMAN_REVIEW`.
9. Concurrency Control: Pessimistic row locking (`SELECT ... FOR UPDATE`) plus a `UniqueConstraint` on `request_id` prevent double-processing; a background Recovery Sweeper (`FOR UPDATE SKIP LOCKED`) reclaims and re-queues `PROCESSING` rows abandoned by a crashed worker.

## 5a-i. Development Phases — Phase 1.B (MCP Security Boundary, In Progress)

1. Authentication: each client (worker type) gets its own bearer token; the server stores only its SHA-256 hash, compares in constant time, and derives `client_id` from the token — never from a caller-supplied header.
2. Per-tool authorization: a server-side allowlist maps `client_id` to permitted tools. Tool listing is filtered by identity; calls to non-allowed tools are rejected and audited as denied.
3. Argument validation: every tool takes a Pydantic model with explicit business limits (e.g., `REFUND_MAX_AMOUNT`), a restricted currency enum, and rejection of unknown fields — enforced server-side regardless of what the LLM produced.
4. Rate limiting: per `client_id` and per tool, computed from the audit table over a sliding window (`MCP_RATE_LIMIT_PER_MIN`), so the limit holds across MCP replicas without adding Redis.
5. Audit log: every invocation (including denied and rate-limited) writes a row with timestamp, `client_id`, tool, arguments (PII masked), decision, and result. See the fail-closed directive in Section 4.

## 5a-ii. Development Phases — Phase 1.C (Containerized Local Deployment, HTTP Reachability Done — Real-Transaction Root Cause Identified, Fix Not Yet Applied)

1. Dockerfiles (done): one image per service under `docker/` — `gateway.Dockerfile`, `worker.Dockerfile` (also used, via command override, for the Recovery Sweeper and a one-shot `migrate` service), `mcp_server.Dockerfile` — each installing only production dependencies as a non-root user.
2. `docker-compose.yml` (done): all seven services (`postgres`, `rabbitmq`, `migrate`, `mcp_server`, `worker`, `sweeper`, `gateway`) orchestrated on a private `agentic_net` bridge network; the `migrate` service runs `alembic upgrade head` and gates the app services via `service_completed_successfully`.
3. Deployment validation (partial): `docker compose up --build` from a clean checkout brings all seven containers up, with the gateway and MCP server reachable across the network. Known pitfall: RabbitMQ's `-q ping` healthcheck can report healthy before the AMQP listener binds — use `check_port_connectivity` instead, and keep a bounded `restart: on-failure:N` on the app services as defense-in-depth against any other first-boot race. HTTP reachability is not the same as a working transaction: a real Worker→MCP-server session failed on nearly every transaction. Root cause identified (not a transport issue): `src/agents/judge.py`'s `evaluate_decision()` calls `get_llm(provider="groq", ...)` with no guard; `langchain-groq` is undeclared, so it `ImportError`s inside the MCP session's `async with` block, which anyio's `TaskGroup` reports as a generic transport failure. See [`docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md`](docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md) for the full diagnosis and the [Microservices Debugging Protocol](docs/architecture/microservices_debugging_protocol.md) for the general practice that found it — isolate the transport plane from the application plane before suspecting Docker networking. Fix proposed (declare the dependency), not yet applied.
4. Load validation (not yet run): re-run the Locust suite (100+ concurrent simulated claimants) against the containerized stack, confirm the Phase 1 pessimistic locks hold without deadlocks, and publish throughput/P95 latency to the README's System Performance table.

## 5a-iii. Development Phases — Phase 1.D (RAG over Business Rules, Done)

RAG is a pattern (embed → store → similarity search → inject into the prompt); AWS Bedrock is a provider. This phase deliberately does not depend on Bedrock — it targets infrastructure already running locally, so it was validated without first configuring AWS IAM/Bedrock access. Migrating the embeddings call to Amazon Titan is Phase 6's job (see Section 5f), not this phase's.

1. Enable `pgvector` + `knowledge_base` table (done, migration `7da4609fe11c`): activates the extension and adds a `knowledge_base` table (`content`, `source`, `source_tier`, `embedding vector(768)`, timestamps) — the `source_tier`/timestamp columns exist specifically to feed Phase 2's fuzzy layer later.
2. Embeddings module (done, `scripts/ingest_knowledge_base.py` + `src/core/services/chunking.py`): vectorizes `docs/policies/refund_policy.md` using `src/agents/llm_factory.py`'s `get_embeddings()` — default Gemini `gemini-embedding-001`, truncated from its native 3072 dims to 768 via `output_dimensionality` — and inserts the chunks into `knowledge_base`. Do not hard-code AWS Bedrock/Titan here.
3. Dynamic context injection (done, `src/worker/worker.py` + `src/core/services/retrieval_service.py`): before the Double Judge call — regardless of `LLM_PROVIDER` — the Worker runs a cosine-similarity search (`KnowledgeBase.embedding.cosine_distance(vector)`, i.e. pgvector's `<=>` operator — not `<->`, which is L2/Euclidean distance and was caught as a mislabel while building this) over `knowledge_base` and injects the matched policy text into `evaluate_decision`'s `context`. Not gated on `LLM_PROVIDER=bedrock`. Fails open on any retrieval error (embeddings API down, DB error) — never blocks transaction processing, mirroring `prompt_guard.py`'s fail-open pattern.
4. This phase feeds the Phase 2 fuzzy layer's inputs (similarity score, freshness, source tier) once both are implemented — do not build Phase 2 scoring logic that assumes retrieval exists before this phase ships it.

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

## 5d. Development Phases — Phase 4 (Ops Dashboard, Experimental)

1. Scope: A read-only React/TypeScript frontend (Transaction Monitor, Confidence Inspector, Quality Trend).
2. Architecture Constraint: The UI must act as an external consumer. It fetches data exclusively from new read-only (GET) endpoints under `api/routers/`. It must never connect directly to the database, the MCP server, or the confidence/observability modules.

## 5e. Development Phases — Phase 5 (ML Comparison Track, Experimental)

1. Scope: An offline TensorFlow/Keras MLP trained on the Phase 2 rule base inputs (`validate_fraud_score` features) to compare its accuracy against the deterministic expert system.
2. Tooling: All training runs and resulting models must be versioned and tracked using MLflow.
3. Architecture Constraint: The MLP is strictly out-of-band. It never participates in the live transaction approval path. Its output is logged solely for offline comparison against the rule base verdicts.

## 5f. Development Phases — Phase 6 (AWS Serverless Migration, Experimental)

1. IAM and Bedrock: least-privilege IAM policies scoped to the foundation models actually invoked, plus VPC PrivateLink endpoints so inference traffic stays in the VPC.
2. Embeddings provider swap: migrate Phase 1.D's embeddings pipeline from Gemini/OpenAI to Amazon Titan Embeddings via Bedrock. This is where Bedrock enters the RAG pipeline — deliberately not in Phase 1.D itself (Section 5a-iii).
3. Serverless topology: FastAPI Gateway → API Gateway, RabbitMQ → SQS, Worker → Lambda.
4. External database: a serverless PostgreSQL provider (Neon or Supabase) with `pgvector` enabled.
5. Re-test of load: repeat the Phase 1.C load validation against the AWS deployment and compare against the local baseline.
6. Dependency order: this phase assumes Phase 1.C (containerization) and Phase 1.D (`pgvector` + a working, provider-agnostic embeddings pipeline integrated locally) are complete — do not begin the Lambda/SQS topology work before both ship.

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
| `RABBITMQ_URL` | RabbitMQ AMQP connection string |
| `LLM_PROVIDER` | Active LLM provider: `gemini`, `groq`, `bedrock`, `openai`, or `vertex` |
| `OPENAI_API_KEY` | OpenAI API key (when LLM_PROVIDER=openai) |
| `GEMINI_API_KEY` | Google GenAI API key |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCP credentials (when using Vertex AI) |
| `GROQ_API_KEY` | Groq API key |
| `AWS_ACCESS_KEY_ID` | AWS key (when LLM_PROVIDER=bedrock) |
| `AWS_SECRET_ACCESS_KEY` | AWS secret (when LLM_PROVIDER=bedrock) |
| `LANGFUSE_SECRET_KEY` | Langfuse telemetry secret |
| `LANGFUSE_PUBLIC_KEY` | Langfuse telemetry public key |
| `MCP_SERVER_URL` | URL of the running MCP server |
| `MAX_LLM_RETRIES` | Maximum retry count for LLM calls (default: 3) |
| `IDEMPOTENCY_TTL_SECONDS` | TTL for idempotency record cache (default: 86400) |
| `MCP_CLIENTS_FILE` | Phase 1.B, server side: path to the client registry (`client_id`, token hash, allowed tools) |
| `MCP_CLIENT_TOKEN` | Phase 1.B, worker side: this worker's bearer token for the MCP server |
| `MCP_RATE_LIMIT_PER_MIN` | Phase 1.B: default calls per minute per client and tool (default: 30) |
| `REFUND_MAX_AMOUNT` | Phase 1.B: upper bound enforced by `execute_refund` validation (default: 10000) |
| `EXPERT_SYSTEM_CONFIDENCE_THRESHOLD` | Phase 2: minimum belief degree required for rule-base auto-approval (default: 0.85) |
| `DRIFT_DETECTOR` | Phase 3: active detector — `ewma`, `cusum`, `page_hinkley`, or `kalman` (default: `ewma`) |
| `EWMA_LAMBDA` | Phase 3: EWMA smoothing factor (default: 0.2) |
| `DRIFT_ALERT_SIGMA` | Phase 3: control-limit width in standard deviations that triggers a drift alert (default: 3.0) |

## 10. Asymmetric Double LLM-as-a-Judge Guardrail Contract

Every LLM decision must pass through the concurrent Double Judge (Gemini + Llama 3 via Groq) before being committed. Both judges evaluate:
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