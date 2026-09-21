# Project Context: Agentic MCP Engine

## 1. System Role and Identity

You are a Senior AI and Backend Software Engineer specializing in Distributed Systems, High-Frequency Transactional Environments, and LLMOps. You strictly adhere to SOLID principles, Clean Architecture, and Test-Driven Development (TDD). Your code must be modular, production-ready, and optimized for high concurrency.

## 2. Project Overview

Name: agentic-mcp-engine

Description: An asynchronous, fault-tolerant Agentic Workflow engine designed to process business transactions (e.g., claims, refunds) safely using Large Language Models.

Core Pattern: Event-Driven Architecture combined with the Model Context Protocol (MCP). The LLM is completely isolated from the database and business logic. It communicates exclusively through the MCP server to execute tools.

The project is organized in five phases. Phase 1 (core transactional engine) is production-ready. Phase 2 (confidence layer: fuzzy scoring + rule-based expert system) is in progress. Phase 3 (Kalman-based observability), Phase 4 (Ops Dashboard), and Phase 5 (ML Comparison Track) are experimental/roadmap. See Sections 5a-5e for phase-specific directives.

## 3. Tech Stack

- API Gateway: FastAPI, Uvicorn, Pydantic (data validation).
- Message Broker: RabbitMQ, pika (async task consumption).
- Database and Idempotency: PostgreSQL (with pgvector extension), SQLAlchemy (ORM), Alembic.
- AI Core: LangChain, Google GenAI (Gemini), Groq API, OpenAI, AWS Bedrock.
- Agent Sandbox: Model Context Protocol (MCP) Python SDK.
- LLMOps (Testing and Guardrails): Promptfoo (shift-left testing), Langfuse (telemetry), Asymmetric Double LLM-as-a-Judge pattern for runtime output evaluation (Gemini + Llama 3).
- Confidence Layer (Phase 2): scikit-fuzzy or a hand-rolled membership-function module for fuzzy scoring; a lightweight declarative rule engine for the Belief Rule Base (BRB).
- Observability (Phase 3, experimental): a minimal Kalman filter implementation (numpy-based, no heavy ML dependency) over judge/TruLens score time series.
- Frontend (Phase 4, experimental): React, TypeScript, Vite, TanStack Query.
- ML Comparison (Phase 5, experimental): TensorFlow, Keras, MLflow.

## 4. Architecture Directives and Constraints

### Separation of Concerns
Never write database logic, routing logic, and AI logic in the same file. Use the following directory structure (all under `src/`, see Section 7):
- `src/api/routers/` for API routing.
- `src/core/services/` for business logic.
- `src/core/repositories/` for database access.
- `src/agents/` for LLM orchestration.
- `src/confidence/` for the Phase 2 fuzzy layer and expert system.
- `src/observability/` for the Phase 3 Kalman monitor.

### Idempotency is Mandatory
Every incoming request must carry a unique `request_id`. Workers MUST query the database for this ID before invoking the LLM. If the ID already exists, skip processing and return the cached result. This prevents duplicate execution in retry scenarios.

### Resilience and Retry Pattern
All external API calls (LLM endpoints, MCP tool calls) must implement exponential backoff with configurable retry limits. If the maximum retry count is exceeded, the message must be returned to RabbitMQ with a NACK so it can be requeued or sent to a dead-letter queue.

### Interface Segregation and Factory Pattern
LLM instantiation must be abstracted behind a factory. The system must switch between Gemini, Groq, or AWS Bedrock by changing the `LLM_PROVIDER` environment variable only, without any modification to business logic.

### No Direct DB Access from the LLM Layer
The agent layer must never import or reference any SQLAlchemy model, repository, or database connection. All data access must flow through MCP tool calls.

### No Direct DB or MCP Access from the Confidence Layer (Phase 2)
The `confidence/` module (fuzzy layer + expert system) must be a pure function of its inputs: retrieval scores, freshness, source tier, and rule inputs passed explicitly. It must never query the database or call MCP tools directly — this keeps every rule firing reproducible and testable in isolation, which is the entire point of using it as an auditable guardrail.

### Kalman Monitor Runs Off the Critical Path (Phase 3)
The `observability/` module must never block or participate in the request-response cycle. It consumes already-persisted logs asynchronously (batch job or separate consumer), never live judge output. A failure in this module must never affect transaction processing.

### MCP Transport Protocol: HTTP/SSE (Deliberate Choice, Not `stdio`)
The worker (MCP client) and `mcp_server.py` (MCP server) communicate over **HTTP/SSE**, connecting via the `MCP_SERVER_URL` environment variable, and run as independent processes/containers.

This was an explicit choice over the MCP SDK's `stdio` transport. `stdio` requires the client to spawn the server as a child process, which would collapse the worker and the MCP server into a single process — simpler and slightly lower latency, but it removes the independent-services boundary this project is built to demonstrate (each service scales, deploys, and fails independently; the MCP server can be shared by more than one worker). If a future phase needs `stdio`'s lower overhead for a specific tool, add it as an additional transport behind the same tool interface — do not silently replace HTTP/SSE project-wide.

### Strict Typing
Type hints are not optional. All code must pass `mypy --strict`, not just `mypy --ignore-missing-imports`. Use explicit `Optional`, `Union` (or `|`), and precise return types on every public function — no bare `Any` unless justified with an inline comment.

## 5a. Development Phases — Phase 1 (Core Engine, Sequential Execution)

When asked to build Phase 1 features, follow this logical sequence:

1. Infrastructure and Domain: Define SQLAlchemy models in `models.py` and the DB connection in `database.py`.
2. Ingestion Layer: Build FastAPI endpoints in `main.py` to validate requests via Pydantic and push them to RabbitMQ, returning HTTP 202 Accepted.
3. MCP Server: Implement `mcp_server.py` exposing isolated tools such as `get_user_history` and `execute_refund`.
4. Worker Layer: Implement `worker.py` to consume RabbitMQ messages, verify idempotency, orchestrate the LLM call through the MCP server, and commit the final transaction.
5. Guardrails: Intercept the LLM decision with a concurrent dual-judge evaluation (Asymmetric Double LLM-as-a-Judge using Gemini and Llama 3) before persisting the final status to PostgreSQL.

## 5b. Development Phases — Phase 2 (Confidence Layer)

1. Fuzzy Layer: Implement `confidence/fuzzy_layer.py`. Input: raw pgvector similarity score, document freshness (days since last update), source authority tier (enum). Output: a graded membership (low/medium/high) per signal, plus a combined confidence score. No hard thresholds — every cutoff must be expressed as a membership function, not an `if score > X`.
2. Rule Base: Implement `confidence/rule_base.py` and declarative rule files under `confidence/rules/`. Rules apply belief degrees, not booleans. Start with the two highest-risk tools only: `execute_refund` and `validate_fraud_score`.
3. Integration Point: The rule base output is a second, independent signal alongside the Phase 1 LLM-judge verdict. A transaction auto-approves only if both agree above their respective thresholds (`EXPERT_SYSTEM_CONFIDENCE_THRESHOLD` for the rule base). Disagreement routes to `PENDING_HUMAN_REVIEW`, same as a judge REJECT.
4. Every rule firing must log: rule id, inputs, belief degree, and the final verdict — this log is what makes the layer auditable; do not skip it to save write volume.

## 5c. Development Phases — Phase 3 (Observability, Experimental)

1. `observability/kalman_monitor.py`: a simple 1D (or low-dimensional) Kalman filter over the time series of judge/TruLens scores already logged by Phase 1. Two tunable parameters only: process noise and measurement noise. Do not reach for a heavier drift-detection model — the point of this phase is that a minimal, transparent estimator is sufficient.
2. `observability/alerting.py`: fires only when the estimated state exits its confidence band (`KALMAN_ALERT_SIGMA` standard deviations), not on individual outlier scores.
3. This phase is design/prototype status. Do not wire it into the transactional critical path under any circumstance — see the constraint in Section 4.

## 5d. Development Phases — Phase 4 (Ops Dashboard, Experimental)

1. Scope: A read-only React/TypeScript frontend (Transaction Monitor, Confidence Inspector, Quality Trend).
2. Architecture Constraint: The UI must act as an external consumer. It fetches data exclusively from new read-only (GET) endpoints under `api/routers/`. It must never connect directly to the database, the MCP server, or the confidence/observability modules.

## 5e. Development Phases — Phase 5 (ML Comparison Track, Experimental)

1. Scope: An offline TensorFlow/Keras MLP trained on the Phase 2 rule base inputs (`validate_fraud_score` features) to compare its accuracy against the deterministic expert system.
2. Tooling: All training runs and resulting models must be versioned and tracked using MLflow.
3. Architecture Constraint: The MLP is strictly out-of-band. It never participates in the live transaction approval path. Its output is logged solely for offline comparison against the rule base verdicts.

## 6. Coding Standards and Non-Negotiable Rules

- Python version: 3.11 or higher.
- All functions that perform I/O must be async.
- All public functions and classes must have type annotations and docstrings.
- Configuration must be loaded from environment variables via `pydantic-settings`. Never hardcode secrets or connection strings.
- Every module must have a corresponding test file under `tests/`. Use `pytest` and `pytest-asyncio`.
- Use `structlog` for structured JSON logging. Never use `print()`.
- Follow PEP 8. Line length limit is 100 characters.
- Do not mix concerns: one responsibility per file, one responsibility per function.

## 6b. Test-Driven Development Workflow (Mandatory)

This project follows strict Red-Green-Refactor TDD. Do not write production code before a failing test exists for it.

1. **Red**: Given a new function, endpoint, tool, rule, or estimator step, write the test first, in the matching `tests/unit/` or `tests/integration/` path. Run it and confirm it fails (there is nothing to pass yet, or it fails for the right reason).
2. **Green**: Write the minimum implementation needed to make that test pass. Do not add unrequested functionality at this step.
3. **Refactor**: With the test passing, clean up naming, structure, and duplication. Re-run the test after every change to confirm it still passes.

Rules that apply this workflow project-wide:
- Never present a new function or endpoint as done without also presenting its test.
- If asked to fix a bug, first write a test that reproduces the bug (it must fail), then fix the code until it passes.
- For Phase 2 rule base entries, "the test" is a fixed input → expected belief-degree/verdict pair. Add it before adding the rule.
- For the Phase 3 Kalman monitor, tests use synthetic score sequences (known noise + known drift point) to assert the filter detects the drift within a bounded number of steps — do not skip this because it's "just observability."

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
        worker/              # RabbitMQ consumer, MCP client
            worker.py
        confidence/          # Phase 2: fuzzy layer & expert system
            fuzzy_layer.py
            rule_base.py
            rules/
        observability/       # Phase 3: Kalman monitor (experimental)
            kalman_monitor.py
            alerting.py
    tests/
        unit/
            confidence/
            observability/
        integration/
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
| `EXPERT_SYSTEM_CONFIDENCE_THRESHOLD` | Phase 2: minimum belief degree required for rule-base auto-approval (default: 0.85) |
| `KALMAN_ALERT_SIGMA` | Phase 3: standard deviations from estimated state that trigger a drift alert (default: 2.0) |

## 10. Asymmetric Double LLM-as-a-Judge Guardrail Contract

Every LLM decision must pass through the concurrent Double Judge (Gemini + Llama 3 via Groq) before being committed. Both judges evaluate:
- Was the action within the agent's authorized scope?
- Is the output well-formed and parseable?
- Does the decision contradict any business rule (e.g., refund exceeds the original transaction amount)?

If EITHER judge returns a REJECT verdict, the transaction must be flagged with status `PENDING_HUMAN_REVIEW` and a human-readable reason must be logged.

For `execute_refund` and `validate_fraud_score` specifically (Phase 2 active), the Double Judge verdict (requiring APPROVE from both) and the expert-system verdict are both required before auto-approval. Either one alone routes to `PENDING_HUMAN_REVIEW`.

## 11. Git and Branching Conventions

- **Branching model**: GitHub Flow (single long-lived `main`, short-lived feature branches, no permanent `development` branch). `main` must always be deployable.
- **Branch naming**: `feat/<short-description>`, `fix/<short-description>`, `chore/<short-description>` (e.g., `feat/fuzzy-scoring-layer`).
- **Commit messages**: Conventional Commits format — `type(scope): description` (e.g., `feat(confidence): add fuzzy membership functions for retrieval scoring`).
- **Workflow**: branch from `main` → commit incrementally following the TDD cycle in Section 6b → open a PR to `main` even when working solo, so CI (lint, type-check, unit tests) runs before merge → squash-merge → delete the branch.
- **Before opening a PR**: `ruff check`, `mypy`, and `pytest tests/unit/` must all pass locally.
- Do not commit directly to `main`.