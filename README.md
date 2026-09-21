# Agentic MCP Engine and RAG Gateway

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg) ![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg) ![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)

## Summary

An asynchronous workflow engine for running LLM agents against transactional business logic (refunds, fraud checks) without giving the model direct access to the database or internal APIs.

It addresses three problems that appear when LLMs are placed in a write path: non-deterministic output, uncontrolled access to side-effecting operations, and synchronous blocking on slow inference calls. The engine combines an event-driven pipeline (FastAPI → RabbitMQ → worker) with a Model Context Protocol (MCP) server as the only route to side-effecting tools. Retrieval over business rules stored in PostgreSQL/pgvector is planned (Phase 1.D), not yet built.

The project also examines a second question: **how much of an AI system's decision-making can be made deterministic and auditable instead of probabilistic?** Later phases add a rule-based confidence layer (fuzzy scoring and a belief rule base) and a drift-detection layer over quality metrics. The direction is consistent throughout: use an explicit, inspectable mechanism wherever one can do the job, and use the LLM only where symbolic reasoning cannot replace it.

---

## Project Status

**What this is**

- A feature-complete core engine that runs locally under `docker compose` (Phase 1.C), with unit tests, integration tests against real PostgreSQL and RabbitMQ, and failure-injection tests.
- A reference architecture with documented design decisions (see [Architecture Decision Records](#architecture-decision-records)).

**What this is not (yet)**

- Not deployed. There is no production deploy target, no CI/CD pipeline, no SLOs, and no incident runbook.
- Not load tested. The Locust suite is a concurrency smoke test against `localhost`; it does not measure capacity under real network, cold-start, or resource-contention conditions.
- Not hardened. The MCP server currently accepts unauthenticated calls; closing this is Phase 1.B.

---

## Tech Stack

| Category | Technologies |
|---|---|
| **Core Framework** | Python 3.10+, FastAPI, Pydantic, Uvicorn |
| **Messaging** | RabbitMQ, aio-pika |
| **State & Persistence** | PostgreSQL, pgvector, SQLAlchemy (async), Alembic |
| **AI & Orchestration** | LangChain, Model Context Protocol (MCP) |
| **RAG Ingestion (Phase 1.D)** | boto3, Amazon Titan Embeddings |
| **LLM Providers** | OpenAI (GPT-4o), Google Vertex AI, Gemini AI Studio, AWS Bedrock, Groq |
| **LLM Evaluation & Tracing** | TruLens, Langfuse (optional), promptfoo |
| **Testing** | Pytest, pytest-cov, Locust |
| **Infrastructure** | Docker, Docker Compose |

---

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Core engine: event-driven pipeline, MCP, guardrails, concurrency control | Feature-complete, running locally |
| **Phase 1.B** | MCP security boundary: authn, per-tool authz, validation, rate limiting, audit log | In progress |
| **Phase 1.C** | Containerized local deployment: per-service Dockerfiles, full `docker-compose` orchestration | Dockerfiles + orchestration + deployment validation done; load validation (Locust) not yet run |
| **Phase 1.D** | RAG over business rules: pgvector + AWS Bedrock (Titan Embeddings) | Not started |
| **Phase 2** | Confidence layer: fuzzy scoring + belief rule base | In progress |
| **Phase 3** | Quality drift detection (pluggable detector) | Designed, not yet implemented |
| **Phase 4** | Read-only operations dashboard | Designed, not yet implemented |
| **Phase 5** | Offline comparison: Keras MLP vs. rule base | Designed, not yet implemented |
| **Phase 6** | Cloud migration: AWS Serverless (API Gateway, SQS, Lambda) | Designed, not yet implemented |

---

## Documentation Index

### Architecture
- **[Phase 1: Core Engine Architecture](docs/phases/phase_1_core_engine.md):** The asynchronous pipeline, event-driven design, and MCP server.
- **[Advanced AI Roadmap](docs/architecture/advanced_ai_roadmap.md):** Research directions for later iterations (constrained decoding, conformal prediction, rule-based reward models).
- **[Deterministic Guardrails Roadmap](docs/deterministic_guardrails_roadmap.md):** Deterministic and auditable mechanisms beyond LLM-as-a-Judge, including classical ML baselines.

### Testing & Reliability
- **[Test Coverage Report](docs/testing/tdd_coverage.md):** Unit and integration test coverage.
- **[Failure Injection Tests](docs/testing/chaos_engineering_armageddon.md):** Ten failure scenarios, their severity, and the invariants each one verifies.
- **[Telemetry & Performance Testing](docs/testing/telemetry_performance.md):** Concurrency testing, coverage, and LLM tracing.

---

## Phase 1 — Core Engine (Feature-complete, running locally)

### Build Sequence
1. **Persistence:** Async PostgreSQL domain models and Alembic migrations.
2. **Ingestion gateway:** FastAPI endpoints validate payloads, publish to RabbitMQ, and return `202 Accepted` immediately.
3. **MCP server:** A separate HTTP/SSE service that is the only component able to execute side-effecting tools.
4. **Worker:** RabbitMQ consumer with idempotency checks in PostgreSQL before any LLM call.
5. **Pre-Execution Shield (Prompt Guard):** A specialized 22M parameter model (`llama-prompt-guard-2-22m`) intercepts malicious prompts and jailbreak attempts before they reach the primary agent, failing fast.
6. **Asymmetric Double LLM-as-a-Judge:** A dual-model jury (Gemini and Groq GPT-OSS) evaluates the primary agent's output concurrently.
7. **Self-Correction Loop:** If the base judges reject a formatting or logic error, the feedback is routed back to the primary agent for self-correction up to `MAX_LLM_RETRIES`.
8. **Cascade Architecture (Supreme Court):** If the base judges disagree or repeatedly reject, the transaction escalates to a Supreme Court Judge (Gemini 3.5 Flash) for a final tie-breaking decision before falling back to `PENDING_HUMAN_REVIEW`.
9. **Provider routing:** Abstract Factory for swapping LLM providers per component, with explicit temperature control.
10. **Concurrency control:** Pessimistic row locking (`SELECT ... FOR UPDATE`) plus a `UniqueConstraint` on `request_id` prevent two workers from processing the same transaction; a background Recovery Sweeper (`FOR UPDATE SKIP LOCKED`) detects `PROCESSING` rows abandoned by a crashed worker and re-queues them.

**Completed in this build sequence:** pessimistic locking and integrity constraints (step 10), the Recovery Sweeper (step 10), the Prompt Guard pre-execution shield (step 5), and the Supreme Court cascade judge (step 8).

### 1. Provider-Agnostic LLM Routing

`src/agents/llm_factory.py` implements an Abstract Factory, so business logic never depends on a specific provider. The provider is selected by environment variable, and different components can use different providers at the same time (for example, GPT-4o for the primary agent and Groq for the judge).

| Provider | Role in this project |
|---|---|
| **OpenAI (GPT-4o)** | Primary agent: tool calling and multi-step reasoning. |
| **Google Vertex AI** | Deployment inside a GCP VPC when data must stay in-perimeter. |
| **Gemini AI Studio** | Primary agent (using `gemini-3.5-flash-lite`) and Judge 1. |
| **AWS Bedrock (Claude 3.5 Sonnet / Llama 3)** | AWS-native inference without data leaving the account. |
| **Groq (Llama 3)** | Judge 2: ultra-low latency and deterministic auditing at temperature 0.0. |
| **Mock** | Offline `FakeListChatModel` returning fixed valid JSON, for local development without token spend. |

### 2. Idempotency and Message Handling

The ingestion gateway publishes each request to RabbitMQ and returns `202 Accepted`. Workers process messages with manual acknowledgment, retry transient LLM failures with exponential backoff, and route exhausted messages to a dead-letter queue.

**Operational contract**

| Property | Guarantee |
|---|---|
| Delivery | At-least-once (RabbitMQ manual ACK). |
| Effect | Exactly-once per `request_id` within the idempotency window: the `request_id` is checked in PostgreSQL before LLM execution, and duplicates are acknowledged without re-execution. |
| Idempotency window | `IDEMPOTENCY_TTL_SECONDS` (default 24 h). A `request_id` replayed after expiry is treated as a new request. |
| Retries | Up to `MAX_LLM_RETRIES` (default 3) with exponential backoff on rate limits and timeouts. |
| Exhausted retries | Message moves to the dead-letter queue; no partial effect is committed. |
| Double Judge rejection | If either Gemini or Groq rejects, the transaction is persisted as `PENDING_HUMAN_REVIEW`; no tool is executed. |
| Stale lock recovery | If a worker crashes mid-flight, the `PROCESSING` row is detected by the Recovery Sweeper (`FOR UPDATE SKIP LOCKED`) and re-enqueued within `SWEEPER_STALE_THRESHOLD_SECONDS` (default 5 min). |

### 3. MCP Server

The LLM never touches the database or internal APIs. It reasons about the request and asks the MCP server to run a tool (`execute_refund`, `validate_fraud_score`). The server is a separate process, so a malformed or hallucinated tool call can only reach what the server exposes. Securing that boundary is Phase 1.B.

### 4. Retrieval over Business Rules

Before calling a transactional tool, the agent is designed to retrieve the relevant business rules by similarity search. This retrieval path is **not yet implemented** — no `pgvector` extension is enabled, no vector column exists on any model, and no embedding pipeline exists yet. Building it is tracked as [Phase 1.D](#phase-1d--rag-over-business-rules-pgvector--aws-bedrock-not-started), below. Phase 1 currently runs without retrieved context.

### 5. Evaluation and Regression

- **Regression:** promptfoo test matrices (100+ edge cases) run against the primary agent and judge prompts, so a prompt change that breaks earlier behavior is caught before merge.
- **Runtime judge:** described in the build sequence above.
- **RAG evaluation:** TruLens measures context relevance, groundedness, and answer relevance, and records per-node latency and token usage.

---

## Phase 1.B — MCP Security Boundary (In progress)

### Problem

The project's central claim is that the MCP server is the only path from the LLM to side-effecting operations. In the current code that path is open: the server accepts unauthenticated HTTP on port 8080, exposes every tool to every caller, relies only on type hints for argument validation, applies no rate limits, and keeps no audit record. Anyone with network access to the server can call `execute_refund` directly, bypassing the agent, the judge, and the rule base.

### Current state

| Control | State |
|---|---|
| Client authentication | Not implemented |
| Per-tool authorization | Not implemented |
| Server-side argument validation | Partial: type hints only, no business limits |
| Rate limiting | Not implemented |
| Audit log | Not implemented (console logs and final transaction state only) |

### Design

1. **Authentication.** Each client (worker type) has its own token. The server stores only SHA-256 hashes of tokens, compares them in constant time, and derives `client_id` from the token, never from a caller-supplied header. Requests without a valid token are rejected before reaching any tool.
2. **Per-tool authorization.** A server-side allowlist maps each `client_id` to the tools it may call. Tool listing is filtered by identity, so a client does not see tools it cannot use, and calls to non-allowed tools are rejected and audited as denied.
3. **Argument validation.** Every tool takes a Pydantic model with explicit constraints: positive amounts bounded by a configurable maximum, currency restricted to an enum, and unknown fields rejected. Validation happens on the server regardless of what the LLM serialized.
4. **Rate limiting.** Limits are per `client_id` and per tool, computed from the audit table over a sliding window. Because the count lives in PostgreSQL, the limit holds across multiple MCP replicas without adding Redis.
5. **Audit log.** Every invocation, including denied and rate-limited ones, writes a row with timestamp, `client_id`, tool, arguments (PII masked), decision, and result status. The MCP server's database role has `INSERT` and `SELECT` on this table but not `UPDATE` or `DELETE`. If the audit write fails, the tool does not execute (fail closed).

### Prompt-injection invariant

Documents retrieved by RAG are untrusted input. The design guarantees one structural property instead of relying on content filtering:

> The set of tools available to a request is determined by the caller's authenticated identity on the server. Nothing in the prompt or in retrieved documents can extend it.

An injected instruction can still influence which of the *allowed* tools the agent chooses and with what arguments; that residual risk is what the argument limits, the judge, and the Phase 2 rule base constrain. A failure-injection test verifies the invariant: a poisoned document instructing a restricted identity to call `execute_refund` must produce a denied, audited call.

### Threat model

| In scope | Out of scope |
|---|---|
| Direct calls to the MCP server from inside the network | Compromise of the host or of the database superuser |
| A worker identity calling tools outside its role | Traffic interception (no TLS between services yet) |
| Runaway agent loops issuing repeated tool calls | Credential rotation and secret management |
| Prompt injection through retrieved documents | Model-provider-side attacks |

---

## Phase 1.C — Containerized Local Deployment (Deployment validation done; load validation pending)

### Problem

Phase 1 ran as four processes started by hand in separate terminals (Postgres, RabbitMQ, MCP server, worker, gateway). `docker-compose.yml` orchestrated only the two infrastructure dependencies (`postgres`, `rabbitmq`); there were no Dockerfiles and no compose entries for the Gateway, Worker, or MCP server themselves, so the "independent services" boundary Phase 1 is built around (see the [HTTP/SSE ADR](#why-httpsse-for-mcp-transport-not-stdio)) was never exercised by an actual deployment.

### Scope

1. **Dockerfiles (done):** one slim `python:3.11` image per service — `docker/gateway.Dockerfile`, `docker/worker.Dockerfile` (also used, via command override, for the Recovery Sweeper and a one-shot `migrate` service), `docker/mcp_server.Dockerfile` — each installing only production dependencies (`pip install .`, not `.[dev]`) and running as a non-root user.
2. **`docker-compose.yml` (done):** all seven services (`postgres`, `rabbitmq`, `migrate`, `mcp_server`, `worker`, `sweeper`, `gateway`) now run on a private `agentic_net` bridge network. The one-shot `migrate` service runs `alembic upgrade head` and gates the app services via `service_completed_successfully`.
3. **Deployment validation (done):** `docker compose up --build` from a clean checkout brings all seven containers to a running state, with the Gateway and MCP server reachable through the network from the host (`/docs` on the gateway, `/sse` on the MCP server). One real bug was found and fixed in the process: RabbitMQ's healthcheck (`rabbitmq-diagnostics -q ping`) reported healthy before the AMQP listener on 5672 was actually accepting connections, so on the very first boot the `worker` and `sweeper` containers hit `Connect call failed`. Fixed by switching the healthcheck to `check_port_connectivity` (which verifies the listener itself, not just that the Erlang node is up) and adding a bounded `restart: on-failure:5` to the app services as defense-in-depth.
4. **Load validation (not yet run):** re-run the Locust concurrency suite (100+ simulated concurrent claimants) against the containerized stack instead of bare `localhost`, confirm the pessimistic locks in Phase 1 hold under contention without deadlocks, and publish the resulting throughput and P95 latency into the [System Performance & Telemetry](#system-performance--telemetry) table, replacing the current placeholder values.

This phase seals the local environment that Phase 1.B secures and Phase 1.D (below) and the AWS migration in [Phase 6](#phase-6--cloud-migration-aws-serverless-designed-not-yet-implemented) build on.

---

## Phase 1.D — RAG over Business Rules (pgvector + AWS Bedrock) (Not started)

### Problem

Phase 1's ["Retrieval over Business Rules"](#4-retrieval-over-business-rules) design describes an agent that looks up relevant policy text before calling a transactional tool. That retrieval path does not exist yet: `pgvector` is not enabled, no model has an embedding column, and there is no ingestion pipeline. Today the agent reasons only from the prompt and the tool arguments.

### Scope

1. **Enable `pgvector`:** an Alembic migration activates the extension and adds the embedding column(s) needed for similarity search.
2. **Embeddings module:** a `boto3`-based script vectorizes business documents (refund and warranty policy text) using Amazon Titan Embeddings and inserts them into `pgvector`, reusing the existing `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` credentials.
3. **Dynamic context injection:** before the primary agent call (when `LLM_PROVIDER=bedrock`), the Worker runs a cosine-similarity search over `pgvector` and injects the matched policy text into the system prompt.

---

## Phase 2 — Confidence Layer (In progress)

Phase 1's LLM-as-a-Judge is useful, but it is still a probabilistic model evaluating another probabilistic model: its verdict cannot be traced to a specific cause and inherits sampling variance. Phase 2 adds a deterministic check next to it, built on classical knowledge-based systems methods rather than statistical inference.

### 1. Fuzzy Scoring over Retrieval

Raw `pgvector` similarity scores are fuzzified instead of cut at a fixed threshold.

- **Inputs:** similarity score, document freshness, source trust tier.
- **Output:** graded membership (low / medium / high relevance) per candidate document.
- **Rationale:** documents near the similarity cutoff are the cases where a hard threshold silently drops relevant rules or admits noise. Graded membership exposes that ambiguity instead of hiding it.

### 2. Belief Rule Base

A rule base built with METHONTOLOGY-style knowledge acquisition (rules elicited from the domain, not learned) sits between the fuzzy layer and the transactional tools.

- Rules carry **belief degrees** instead of strict boolean IF-THEN, so partially matching conditions produce a graded confidence rather than an arbitrary tie-break.
- Applied to the two highest-risk tools, `execute_refund` and `validate_fraud_score`. A transaction proceeds automatically only when the judge and the rule base both clear their thresholds; disagreement routes to human review.
- Every rule firing is logged with its inputs and belief degree, so each approval can be reconstructed afterward.

### 3. Relation to the LLM-Judge

The judge stays useful for open-ended checks (tone, completeness, groundedness). The rule base is not a better judge; it is a different kind of check: deterministic, traceable, and independent of sampling variance. For actions with direct financial consequences, having one non-probabilistic gate in the approval path is a real risk reduction.

It also has a cost effect: the rule base runs with zero inference cost, and cases it resolves with high confidence can skip judge escalation paths (see [Cost per Transaction](#cost-per-transaction)).

---

## Phase 3 — Quality Drift Detection (Designed, not yet implemented)

Phase 1's evaluation scores individual runs; it cannot tell a sustained decline from normal request-level noise. Phase 3 treats the per-request judge and RAG scores as a time series and raises an alert only on a sustained shift. It runs asynchronously on the logs Phase 1 already produces, off the transactional path.

The detector is pluggable (`DRIFT_DETECTOR`), with EWMA as the default:

| Detector | Detects best | Assumptions | Parameters |
|---|---|---|---|
| **EWMA** (default) | Gradual drift | Approximately stationary in-control mean and variance | Smoothing λ, control-limit width L |
| **CUSUM** | Abrupt step changes (prompt deploy, model or provider switch) | Known or estimated in-control mean; target shift size | Reference k, threshold h |
| **Page-Hinkley** | Step changes, online, without a fixed in-control mean | Mean shift in one direction per detector | Tolerance δ, threshold λ |
| **Kalman filter** | Tracking a latent quality state with an explicit uncertainty band | Linear-Gaussian state and measurement model | Process noise Q, measurement noise R |

See the ADR on drift detection for why EWMA is the default.

---

## Phase 4 — Operations Dashboard (Designed, not yet implemented)

The auditability from Phases 1.B and 2 currently lives in logs and tables. Phase 4 is a small read-only UI that makes it visible.

- **Screens:** transaction monitor (status, judge verdict, rule-base verdict, with `PENDING_HUMAN_REVIEW` highlighted); decision inspector (rules fired, belief degrees, inputs, audit entries); quality trend (raw scores vs. detector output and alerts).
- **Stack:** React, TypeScript, Vite, TanStack Query, Recharts, Tailwind CSS.
- **Real-time updates:** the transaction table reflects new/changed rows via WebSocket, SSE, or polling against the read-only endpoints — mechanism to be decided during implementation.
- **Visual metrics:** throughput, P95 latency, and approved-vs-rejected refund rate, sourced from the same tables the [Cost per Transaction](#cost-per-transaction) and [System Performance & Telemetry](#system-performance--telemetry) sections report manually today.
- **In scope:** read-only `GET` endpoints under `src/api/routers/`; the UI is an ordinary API consumer.
- **Out of scope:** write actions, its own auth system, global state libraries, direct access to the database, MCP tools, or the confidence and observability modules.

---

## Phase 5 — Offline Comparison: MLP vs. Rule Base (Designed, not yet implemented)

An offline experiment that tests the project's core argument instead of asserting it: does a black-box model beat the belief rule base on `validate_fraud_score`, by how much, and at what cost to auditability?

- **Model:** Keras Sequential MLP (2–3 dense layers) trained on the same features the rule base consumes.
- **Evaluation:** precision, recall, and F1 on the same labeled cases used to validate the rules.
- **Tracking:** MLflow records hyperparameters, metrics, and the model artifact per run, so each prediction is attributable to a specific model version.
- **Constraint:** the MLP never participates in the approval path. Its predictions are logged next to the rule-base verdict for comparison only, and surfaced as a panel in the Phase 4 dashboard.

---

## Phase 6 — Cloud Migration (AWS Serverless) (Designed, not yet implemented)

The end state for this project is not a container running on one machine; it is a deployment that costs approximately $5/month, or $0 within free-tier limits, and survives the machine being turned off. Phase 6 re-targets the Phase 1.C container topology at managed AWS services once the local stack, its security boundary, and its load characteristics are proven.

- **IAM and Bedrock:** least-privilege IAM policies scoped to the foundation models the project actually invokes, plus VPC PrivateLink endpoints so inference traffic does not leave the VPC.
- **Serverless topology:** FastAPI Gateway → API Gateway, RabbitMQ → SQS, Worker → Lambda.
- **External database:** a serverless PostgreSQL provider (Neon or Supabase) with `pgvector` enabled, chosen to keep the always-on cost at or near $0.
- **Re-test of load:** repeat the Phase 1.C load validation against the AWS deployment and compare throughput/latency against the local baseline.

This phase depends on Phase 1.C (containerization) and Phase 1.D (pgvector/Bedrock already integrated locally) being complete first.

---

## Cost per Transaction

In a transactional system, cost per request is a first-class metric alongside latency.

**Status: pending measurement.**

| Stage | Model | Tokens in | Tokens out | Cost / request (USD) |
|---|---|---|---|---|
| Retrieval (embedding) | XX | XX | — | X.XXXX |
| Primary agent | XX | XX | XX | X.XXXX |
| LLM-as-a-Judge | XX | XX | XX | X.XXXX |
| Rule base (Phase 2) | — | 0 | 0 | 0.0000 |
| **Total** | | **XX** | **XX** | **X.XXXX** |

Method: token counts taken from each provider's usage fields, logged per request, averaged over the promptfoo regression suite; prices from provider list pricing at the date of measurement.

---

## System Performance & Telemetry

**Status: pending measurement.** The table is intentionally kept as a placeholder until real numbers are available.

| Metric | Value |
|---|---|
| Test coverage (unit + integration) | XX.X% |
| API ingestion latency, P95 (FastAPI → RabbitMQ) | XX ms |
| Ingestion throughput (local, concurrency smoke test) | XX req/s |
| End-to-end processing time (LLM-dependent) | ~X.X s |

---

## Testing

### Unit and Integration
Code is developed test-first (Red-Green-Refactor).

- **Unit:** provider factory, judge parsing and routing, confidence layer.
- **Integration:** API gateway, PostgreSQL persistence, MCP server, and worker idempotency, against real infrastructure.

See the [Test Coverage Report](docs/testing/tdd_coverage.md).

### Failure Injection
Ten failure scenarios, ranked by severity from throughput degradation (SEV-3) to risk of data loss or duplicated effects (SEV-1). They include RabbitMQ crashes, idempotency failures in PostgreSQL, provider rate limits, and adversarial prompts.

Each test follows the same cycle: inject the failure, isolate the affected component, verify that invariants hold (no duplicate effect, no lost message, no unauthorized tool call), and verify recovery without state loss.

See [Failure Injection Tests](docs/testing/chaos_engineering_armageddon.md).

### Running Tests

```bash
# Full suite
pytest tests/ -v --tb=short

# Unit tests only (no infrastructure required)
pytest tests/unit/ -v

# Integration tests (requires Docker infrastructure)
pytest tests/integration/ -v

# Phase 2 confidence layer
pytest tests/unit/confidence/ -v

# Coverage
pytest --cov=src tests/ --cov-report=term-missing

# Concurrency smoke test (local only; not a capacity measurement)
locust -f tests/performance/locustfile.py --headless -u 100 -r 10 --run-time 1m --host http://localhost:8000
```

### Linting and Type Checking

```bash
ruff check src/
mypy src/ --strict
```

---

## Project Structure

The project uses the `src/` layout so every internal import is absolute (`from src.core import database`) and resolves the same way in local runs, tests, and Docker.

```
agentic-mcp-engine/
    src/
        api/                  FastAPI entry points
            routers/          Route definitions
            main.py           Application entry point
        core/                 Shared domain logic
            config.py         pydantic-settings configuration
            database.py       Async connection and session
            models.py         SQLAlchemy models
            services/         Business logic
            repositories/     Database access
        agents/               LLM orchestration and provider factory
        mcp_server/           MCP server (HTTP/SSE)
            mcp_server.py
            tools/            Tool implementations
            security/         [Phase 1.B] authn, authz, rate limiting, audit
        worker/               RabbitMQ consumer, orchestration, MCP client
            worker.py
        confidence/           [Phase 2] Fuzzy scoring + belief rule base
            fuzzy_layer.py
            rule_base.py
            rules/            Declarative rule files (refunds, fraud)
        observability/        [Phase 3] Drift detection
            detectors/        EWMA, CUSUM, Page-Hinkley, Kalman
            alerting.py
    tests/
        unit/
            confidence/
            observability/
            security/
        integration/
        performance/
    alembic/
    alembic.ini
    .agents/                  AI coding-agent configuration
    .env.example
    requirements.txt
    docker-compose.yml
    Dockerfile
```

---

## AI-Assisted Development

The project is developed alongside AI coding agents (Gemini Antigravity and Claude Code). The `.agents/` directory holds the configuration that keeps them within the project's conventions.

### Skills (procedures the agent follows)
- **`new-feature`:** Ten-step sequence for adding a feature while respecting layer isolation (routers → services → repositories).
- **`add-mcp-tool`:** Checklist for adding an MCP tool without breaking running agents.
- **`db-migration`:** Safe Alembic practices, including `pgvector` columns.
- **`debug-worker`:** Diagnosis of RabbitMQ queue and idempotency issues.
- **`tests`:** Local validation (`ruff`, `mypy`, `pytest`) before committing.
- **`commit`:** Reviews changes and writes a Conventional Commits message.
- **`ship`:** Tests, lint, commit, and push if everything passes.
- **`push-dev`:** Commit and push without validation, for work-in-progress branches only.
- **`trash`:** Discards a failed attempt (`git restore` and `git clean`).

### Hooks
- **`safety_guard` (pre-tool):** Pauses for manual confirmation before destructive commands (SQL `DROP`, `rm -rf`) or edits to critical files.
- **`lint_check` (post-tool):** Runs `ruff` and `mypy` after every Python edit and feeds errors back to the agent.
- **`context_injector` (pre-invocation):** Periodically restates the architectural rules (for example, no business logic in routers).

### Rules
`workspace.md` holds persistent guidelines, such as mandatory type annotations and no blocking I/O.

---

## Quick Start (Docker)

### 1. Clone and configure

```bash
git clone https://github.com/agustindiazcano/agentic-mcp-engine.git
cd agentic-mcp-engine
cp .env.example .env
```

Fill in `.env` (see [Environment Variables](#environment-variables)).

### 2. Install dependencies

```bash
pip install -e .[dev]
```

### 3. Start the full stack

```bash
docker compose up --build
```

This builds and starts all seven services — `postgres`, `rabbitmq`, a one-shot `migrate` step (`alembic upgrade head`), `mcp_server`, `worker`, `sweeper`, and `gateway` — on a private network (Phase 1.C).

API at `http://localhost:8000`, interactive docs at `http://localhost:8000/docs`. RabbitMQ management UI at `http://localhost:15672`.

### Local development (without rebuilding containers)

To iterate on Python code without rebuilding images each time, start only the infrastructure in Docker and run the services directly:

```bash
docker compose up -d postgres rabbitmq
alembic upgrade head
python -m src.mcp_server.mcp_server      # terminal 2
python -m src.worker.worker              # terminal 3
uvicorn src.api.main:app --reload --port 8000  # terminal 4
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `RABBITMQ_URL` | Yes | RabbitMQ AMQP connection string |
| `LLM_PROVIDER` | Yes | `gemini`, `groq`, `bedrock`, or `openai` |
| `OPENAI_API_KEY` | Conditional | Required when `LLM_PROVIDER=openai` |
| `GEMINI_API_KEY` | Conditional | Required for Gemini AI Studio |
| `GOOGLE_APPLICATION_CREDENTIALS` | Conditional | Required for Vertex AI |
| `GROQ_API_KEY` | Conditional | Required when `LLM_PROVIDER=groq` |
| `AWS_ACCESS_KEY_ID` | Conditional | Required when `LLM_PROVIDER=bedrock` |
| `AWS_SECRET_ACCESS_KEY` | Conditional | Required when `LLM_PROVIDER=bedrock` |
| `LANGFUSE_SECRET_KEY` | No | Langfuse tracing secret key |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse tracing public key |
| `MCP_SERVER_URL` | Yes | URL of the MCP server |
| `MAX_LLM_RETRIES` | No | Maximum LLM retries (default: 3) |
| `IDEMPOTENCY_TTL_SECONDS` | No | Idempotency window in seconds (default: 86400) |
| `MCP_CLIENTS_FILE` | Yes (1.B) | Server side: path to the client registry (`client_id`, token hash, allowed tools) |
| `MCP_CLIENT_TOKEN` | Yes (1.B) | Worker side: this worker's bearer token for the MCP server |
| `MCP_RATE_LIMIT_PER_MIN` | No (1.B) | Default calls per minute per client and tool (default: 30) |
| `REFUND_MAX_AMOUNT` | No (1.B) | Upper bound enforced by `execute_refund` validation (default: 10000) |
| `EXPERT_SYSTEM_CONFIDENCE_THRESHOLD` | No (2) | Minimum belief degree for auto-approval (default: 0.85) |
| `DRIFT_DETECTOR` | No (3) | `ewma`, `cusum`, `page_hinkley`, or `kalman` (default: `ewma`) |
| `EWMA_LAMBDA` | No (3) | EWMA smoothing factor (default: 0.2) |
| `DRIFT_ALERT_SIGMA` | No (3) | Control-limit width in standard deviations (default: 3.0) |

---

## Architecture Decision Records

### Why RabbitMQ over Kafka?

The workload is transactional (claims, refunds): per-message acknowledgment, dead-letter routing, and low delivery latency matter more than high-throughput log streaming. AMQP's per-message ACK/NACK maps directly onto the idempotency and retry contract.

### Why the `src/` layout?

With `app/`, `mcp_server/`, `worker/`, `confidence/`, and `observability/` at the repository root, import resolution depended on the working directory: an import that worked in one launch mode raised `ModuleNotFoundError` in another, and behaved differently again inside Docker. Nesting everything under `src/` makes imports absolute and consistent everywhere, at the cost of one path segment.

### Why HTTP/SSE for MCP transport, not `stdio`?

`stdio` is lighter but requires the client to spawn the server as a child process, which collapses the worker and the MCP server into one process. Keeping them as separate services over HTTP/SSE preserves independent deploys, independent scaling, and several workers sharing one MCP server. `stdio` is the right choice for a single-process CLI tool, not for this system.

### Why MCP over direct function calling?

With direct function calling, tool execution runs inside the process that holds the model's output, so validation and access control depend on that process behaving correctly. MCP puts tool execution behind a separate service that validates inputs, enforces authorization, and logs every call on its own, regardless of what the model produced. This only holds once the server itself is secured, which is why Phase 1.B exists.

### Why enforce authorization on the MCP server, not in the prompt?

Any restriction expressed in the prompt can be overridden by content that reaches the model, including retrieved documents. Authorization tied to the caller's authenticated identity, enforced by a separate process, cannot be changed by anything the model reads. This is what makes the prompt-injection invariant structural rather than heuristic.

### Why rate limiting and audit in PostgreSQL, not Redis or log files?

The audit table has to exist anyway, and counting recent rows in it gives a rate limit that holds across MCP replicas without another piece of infrastructure. A log file is neither queryable nor protected from edits by the process that writes it; an insert-only database role is. Trade-off: one extra query per tool call, and concurrent calls near the limit can overshoot it slightly. Both are acceptable at this system's call volume.

### Why pgvector over a dedicated vector database?

Embeddings live in the same PostgreSQL instance as transaction data, so a single transaction can join semantic search results with live business state. A separate vector database would require a distributed join.

### Why a cheap, fast model for the judge?

The judge runs on every transaction, and its output is short and structured (a verdict and reasons). Its task is classification against explicit policy, not open-ended reasoning, so a smaller model on low-latency hardware (Groq) fits it well. Latency is one reason; cost is the other and matters as much, because the judge's cost is multiplied by total volume, while the primary agent's reasoning is what actually benefits from a larger model.

### Why a rule-based expert system alongside the LLM-judge? (Phase 2)

The judge is a probabilistic model: its verdict cannot be traced to a specific cause and inherits sampling variance. For the two highest-risk tools, the system adds a deterministic gate with explicit, human-authored conditions and belief degrees. This does not make the whole system explainable (the generation step remains opaque), but it makes the approval decision for financial actions independently auditable.

### Why EWMA as the default drift detector, with Kalman as an option? (Phase 3)

The problem is separating sustained quality shifts from request-level noise, which is standard statistical process control. The choice follows parsimony: use the simplest detector that solves the problem, and move to a heavier one only when evidence shows the simpler one fails.

- **EWMA** needs one smoothing parameter and no state-space model, and detects gradual drift. It is the default.
- **CUSUM** and **Page-Hinkley** are better suited to abrupt step changes, which are the most likely failure mode here: a prompt deploy, a model version change, or a provider switch. Choose one of them when changes are expected to be discrete.
- **Kalman** is optional. It gives an explicit uncertainty band on a latent quality state, which EWMA does not, but it assumes a linear-Gaussian state and measurement model. Quality scores are bounded in [0, 1] and often skewed, so that assumption has to be checked on real data before relying on it.

A trained drift classifier was rejected: it would need its own training data and maintenance, and would be another opaque component to monitor.

---

## Research Directions

Beyond the phases above, the following are candidate directions, not planned work. Details in the [Advanced AI Roadmap](docs/architecture/advanced_ai_roadmap.md).

- **Constrained decoding:** mask logits with a finite-state machine so tool-call output is valid by construction.
- **Programmatic prompt optimization:** treat prompts as parameters tuned against the regression suite (for example, DSPy).
- **Conformal prediction:** calibrated error bounds (α) to decide when to delegate to a human.
- **Search-based reasoning:** tree search with explicit value functions for multi-step decisions.
- **Rule-based reward models:** alignment signals from code evaluators instead of learned preference models.

---

## Known Limitations

- Single-node `docker compose` deployment; no orchestration, autoscaling, or high availability until Phase 6.
- No TLS between internal services; no credential rotation or secret manager (tokens are read from environment and files).
- No multi-tenancy; one set of business rules per deployment.
- A database superuser can still modify the audit table; the log is protected against the MCP service, not against a compromised host.
- Evaluation uses a project-specific regression suite of 100+ cases; results do not transfer to other domains without new test data.
- Performance and cost figures are not yet measured (see tables above).

---

## Author

Agustin Diaz-Cano, MS Candidate

---

## License

MIT. See [LICENSE](LICENSE).