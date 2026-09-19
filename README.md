# Agentic MCP Engine and RAG Gateway

## Executive Summary

An enterprise-grade, asynchronous Agentic Workflow Engine designed to safely orchestrate Large Language Models (LLMs) in high-concurrency transactional environments.

This architecture solves the core bottlenecks of deploying Generative AI in production: non-deterministic volatility, data leakage, and synchronous blocking. By combining Event-Driven Architecture (EDA), the Model Context Protocol (MCP), and Advanced RAG, this engine provides a fault-tolerant sandbox for AI agents to interact with business logic.

Beyond the core transactional engine, this project explores a second question: **how much of an AI system's decision-making can be made deterministic and auditable, instead of purely probabilistic?** Phases 2 and 3 extend the engine with a confidence layer (fuzzy logic + rule-based expert system) and a production observability layer (Kalman filtering over quality metrics), moving the system progressively from "trust the LLM's judgment" toward "trust an explicit, inspectable mechanism, and use the LLM only where symbolic reasoning cannot substitute for it."

---

## Roadmap Overview

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Core transactional engine (EDA, MCP, RAG, LLMOps) | Production-Ready |
| **Phase 2** | Confidence layer (fuzzy scoring + expert system) | In Progress |
| **Phase 3** | Observability layer (Kalman-based drift detection) | Experimental / Roadmap |
| **Phase 4** | Ops Dashboard (Read-only React UI) | Experimental / Roadmap |
| **Phase 5** | ML Comparison Track: TensorFlow/Keras MLP | Experimental / Roadmap |

---

## Phase 1 — Core Engine (Production-Ready)

### 1. Provider-Agnostic LLM Routing (SOLID Principles)

Built with an abstract Factory Pattern, the system is fully decoupled from the underlying AI provider. By modifying a single environment variable, the engine dynamically routes inference requests without altering any business logic:

- GCP Vertex AI / Gemini API
- AWS Bedrock (Claude 3.5 Sonnet / Llama 3)
- Groq (ultra-low latency Llama 3.3)

### 2. Transactional Idempotency and Message Queues

- **Asynchronous Ingestion**: FastAPI gateway offloads high-volume RESTful requests to RabbitMQ, returning immediate `202 Accepted` responses.
- **State Management**: Workers enforce strict idempotency via PostgreSQL. Every `request_id` is validated before LLM execution, guaranteeing that financial or business transactions are never duplicated, even during network retries.
- **Resilience**: Implements exponential backoff and Dead Letter Queues (DLQ) for handling LLM API rate limits and timeouts.

### 3. Model Context Protocol (MCP) Sandbox

LLMs are completely isolated from the database and internal APIs. The agent reasons about the user's intent and requests tool execution via a secure MCP Server. This limits the blast radius of hallucinations and enforces strict access control over system tools such as `execute_refund` and `validate_fraud_score`.

### 4. High-Precision RAG (Retrieval-Augmented Generation)

Before executing transactional tools, the agent retrieves domain-specific business rules.

- **Vector Store**: PostgreSQL with the `pgvector` extension for embedding storage, eliminating the need for a separate vector database.
- **Semantic Chunking**: Advanced document chunking strategies (recursive character splitting with semantic overlap) to preserve context continuity.

### 5. LLMOps, Observability, and Testing

Treating prompts as code and LLMs as volatile microservices.

- **Shift-Left Testing**: Automated regression matrices using Promptfoo integrated into the CI/CD pipeline to validate tool-calling accuracy.
- **Runtime Guardrails (LLM-as-a-Judge)**: A secondary, deterministic-configuration model intercepts the primary agent's output, evaluating it against security policies before committing the transaction to the database.
- **Evaluation**: TruLens integration to measure the RAG Triad (Context Relevance, Groundedness, and Answer Relevance).

---

## Phase 2 — Confidence Layer (In Progress)

Phase 1's LLM-as-a-Judge guardrail is a strong safety net, but it is still a probabilistic model evaluating the output of another probabilistic model — useful, but not fully auditable on its own. Phase 2 adds a second, deterministic guardrail that sits alongside it, built on classical knowledge-based systems methodology rather than statistical inference.

### 1. Fuzzy Scoring over Retrieval

Raw `pgvector` similarity scores are fuzzified instead of cut at a hard threshold:

- Inputs: retrieval similarity score, document freshness, source authority/trust tier.
- Output: a graded membership (e.g. low / medium / high relevance) per candidate document, instead of a binary "included / excluded" decision.
- Rationale: business-rule documents near the similarity cutoff are exactly the cases where a hard threshold silently drops relevant context or lets in noise. Grading membership surfaces that ambiguity instead of hiding it.

### 2. Rule-Based Expert System (Belief Rule Base)

A rule base, built with classical METHONTOLOGY-style knowledge acquisition (domain rules elicited explicitly, not learned), sits between the fuzzy layer and the transactional MCP tools:

- Rules are expressed with **belief degrees** rather than strict IF-THEN booleans, so overlapping or partially-matching conditions produce a graded confidence instead of an arbitrary tie-break.
- Applied specifically to the highest-risk tools: `execute_refund` and `validate_fraud_score`. A transaction only proceeds automatically when both the LLM-judge and the expert system agree above their respective confidence thresholds; disagreement routes to human review.
- Every rule firing is logged with its inputs and belief degree — fully inspectable after the fact, which the LLM-judge's raw score is not.

### 3. Why This Complements, Not Replaces, the LLM-Judge

The LLM-judge remains useful for open-ended quality assessment (tone, completeness, groundedness). The expert system is not a better LLM-judge — it is a different kind of check: deterministic, rule-traceable, and independent of model sampling variance. For transactional tools where an incorrect action has direct financial consequences, having one non-probabilistic gate in the approval path is a meaningful risk reduction, not a redundant one.

---

## Phase 3 — Observability Layer (Experimental / Roadmap)

Phase 1's TruLens/Promptfoo evaluation is point-in-time: it scores a given run, but says nothing about whether quality is trending down over days or weeks versus fluctuating with normal noise. Phase 3 proposes closing that gap.

### Kalman-Filtered Quality Monitoring

- The per-request scores already produced by the LLM-judge and the RAG Triad (Phase 1) are treated as a noisy time series.
- A Kalman filter estimates the underlying "true" quality state and its uncertainty band, smoothing request-level noise instead of reacting to individual outliers.
- **Alerting** fires only when the estimated state exits its confidence band — i.e., when there is a real, sustained shift, not a single bad batch.
- This runs asynchronously, off the transactional critical path, consuming the same logs Phase 1 already produces — no additional instrumentation of the core engine is required.

### Status

This phase is a design proposal, not yet implemented. It is included here to document the intended evolution of the system's observability strategy and to scope future work.

---

## Phase 4 — Ops Dashboard (Experimental / Roadmap)

Phases 2 and 3 are only valuable as an "auditable" system if that auditability is actually visible somewhere — today, it lives in logs. Phase 4 is a deliberately small, read-only React + TypeScript dashboard that surfaces what the backend already computes, without introducing a second product surface to maintain.

### Scope (Read-Only, 3 Screens)
- **Transaction Monitor**: Table of recent transactions: request_id, status, timestamp, LLM-judge verdict, expert-system verdict. Filterable by status, with PENDING_HUMAN_REVIEW surfaced prominently.
- **Confidence Inspector (Phase 2)**: Per transaction: which rule fired, its belief degree, and the inputs that triggered it. This is the "auditable decision" argument from Phase 2 made visible, not just claimed in documentation.
- **Quality Trend (Phase 3)**: Chart of the raw judge score time series vs. the Kalman-smoothed estimate and its confidence band. Visual marker where the estimate exits the band and an alert fired.

### Suggested Stack
- **React + TypeScript + Vite**
- **TanStack Query** to consume the backend API directly — no duplicated business logic on the frontend
- **Recharts** (or an equivalent lightweight charting library) for the Kalman band visualization
- **No heavy global state** (Redux/Zustand) — unnecessary for a read-only dashboard

### Architectural Constraint
The dashboard is treated like any other external API consumer: it talks only to new, explicit read-only (GET) endpoints under `src/api/routers/`, and never touches the database, the MCP tools, or the confidence/observability modules directly. This keeps the isolation boundaries already enforced elsewhere in the system (Section 4) intact — the UI does not get a special-case exception.

### Status
This phase is a design proposal, not yet implemented. No read-only endpoints or frontend code exist yet; this section scopes intended future work.

---

## Phase 5 — ML Comparison Track: TensorFlow/Keras MLP (Experimental / Roadmap)

Phase 5 is an offline, out-of-band experiment: a Multilayer Perceptron (MLP), trained with TensorFlow/Keras on the same inputs used by the Phase 2 rule base (`validate_fraud_score`), built to empirically compare a black-box statistical model against the deterministic, auditable expert system — not to replace it.

### Purpose
The project's core argument (Section 4, Phase 2 ADRs) is that an explicit, rule-traceable mechanism is preferable to an opaque probabilistic one wherever it can achieve comparable results. Phase 5 tests that argument directly instead of asserting it: does an MLP outperform the belief-rule-base on this task, and if so, by how much, and at what cost to auditability? This is also a deliberate, hands-on space to practice TensorFlow/Keras fundamentals (MLP architecture, training loops, evaluation) on a dataset tied to the rest of the project, rather than an unrelated toy problem.

### Scope
- **Training**: an offline script/notebook, not a production service. A simple Keras Sequential MLP (2-3 dense layers) trained on the same feature set the Phase 2 rule base consumes.
- **Evaluation**: standard classification metrics (precision, recall, F1) computed against the same labeled cases used to validate the expert system's rules, so the two approaches are compared on identical ground truth.
- **Comparison surface**: MLP prediction and expert-system verdict are logged side by side for the same transactions, and surfaced in the Phase 4 dashboard as a comparison panel — no new screen required.
### Model Versioning and Tracking
Each training run is tracked with MLflow: hyperparameters, evaluation metrics, and the resulting model artifact are logged per run, so a specific MLP prediction can always be traced back to the exact model version and training configuration that produced it. This is what makes the comparison in the Phase 4 dashboard meaningful over time — as the rule base evolves (Phase 2) and the MLP is retrained, both sides of the comparison remain attributable to a specific, reproducible version rather than "whatever was last trained."

### Architectural Constraint
The MLP is strictly out-of-band: it never participates in the real approval path for `execute_refund` or `validate_fraud_score`, and it never gates a transaction. Its output is logged for comparison only. This preserves the guarantee from Phase 2 — every transaction that auto-approves still does so through the LLM-judge and the auditable rule base, never through the black-box model.

### Status
This phase is a design proposal, not yet implemented. It exists to scope a future hands-on ML/MLOps track (model training, versioning, and comparison tracking) without touching the transactional decision path.

---

## Project Structure

This project follows the `src/` layout: all application code lives inside `src/`, giving every internal import an absolute, unambiguous path (`from src.core import database`) and avoiding `PYTHONPATH`/`ModuleNotFoundError` issues across local runs, tests, and Docker.

```
agentic-mcp-engine/
    src/
        api/                 FastAPI entrypoints
            routers/         API route definitions
            main.py          FastAPI application entry point
        core/                Shared domain logic
            config.py        pydantic-settings configuration
            database.py      Async database connection and session
            models.py        SQLAlchemy domain models
            services/        Business logic layer
            repositories/    Database access layer (SQLAlchemy)
        agents/              LLM orchestration and factory
        mcp_server/          MCP server entry point and tool registry (HTTP/SSE)
            mcp_server.py
            tools/           Individual MCP tool implementations
        worker/              RabbitMQ consumer and LLM orchestrator, MCP client
            worker.py
        confidence/          [Phase 2] Fuzzy scoring + expert system rule base
            fuzzy_layer.py   Membership functions over retrieval signals
            rule_base.py     Belief Rule Base (BRB) engine and rule definitions
            rules/           Declarative rule files (per domain: refunds, fraud)
        observability/       [Phase 3, experimental] Kalman-based drift detection
            kalman_monitor.py    State estimator over judge/TruLens score series
            alerting.py          Drift alert dispatch
    tests/
        unit/
            confidence/      Phase 2 unit tests
            observability/   Phase 3 unit tests
        integration/         End-to-end tests (real infrastructure)
    alembic/                 Database migration files
    alembic.ini
    .agents/                 AI agent configuration (skills, hooks, rules)
    .env.example             Environment variable reference
    requirements.txt         Python dependencies
    docker-compose.yml       Local infrastructure (PostgreSQL, RabbitMQ)
    Dockerfile               Application container definition
```

---

## AI-Assisted Development Environment

This project is configured to be developed alongside AI coding agents (Gemini Antigravity and Claude Code). The `.agents/` directory contains custom configurations that turn the AI into a project expert.

### 1. Skills (Runbooks for the AI)
Skills are step-by-step guides that teach the AI how to perform complex, project-specific tasks. Instead of guessing how to do something, the AI reads the skill and follows our exact procedure.
- **`new-feature`**: Teaches the AI the exact 10-step sequence to build a feature, ensuring it respects our layer isolation (routers -> services -> repositories).
- **`add-mcp-tool`**: A checklist for safely adding a new tool to the MCP server without breaking live agents.
- **`db-migration`**: Enforces safe Alembic migration practices, especially for `pgvector` columns.
- **`debug-worker`**: A troubleshooting guide the AI can use to diagnose RabbitMQ queue issues or idempotency failures.
- **`trash`**: A shortcut skill (`/trash`) that allows you to quickly tell the AI to run `git restore` and `git clean` if a feature attempt goes wrong.
- **`tests`**: A runbook to execute local validation (`ruff`, `mypy`, `pytest`) before making a commit.
- **`commit`**: Reviews changes, generates a Conventional Commits message, and commits safely.
- **`ship`**: The complete workflow (`/ship`): runs tests, lints, commits, and pushes the code if everything is green.
- **`push-dev`**: Bypasses all validation checks (`/push-dev`) to commit and push immediately to GitHub.

### 2. Hooks (Automatic Safety Nets)
Hooks are scripts that run automatically at specific moments during the AI's execution to enforce safety and quality.
- **`safety_guard` (Pre-Tool)**: Before the AI executes a shell command or modifies a critical file, this hook intercepts it. If the AI tries to run a destructive command (like a SQL `DROP` or `rm -rf`), the hook pauses the AI and asks you for manual confirmation.
- **`lint_check` (Post-Tool)**: Every time the AI writes Python code, this hook automatically runs `ruff` and `mypy` in the background and reports any errors back to the AI so it can fix them immediately.
- **`context_injector` (Pre-Invocation)**: Periodically reminds the AI of the core architectural rules (like "never put business logic in a router") so it doesn't forget them during long coding sessions.

### 3. Rules
The `workspace.md` file contains persistent guidelines the AI must always follow, such as requiring type annotations and forbidding the use of blocking I/O functions.

---

## Quick Start (Dockerized Environment)

The infrastructure is fully containerized for a deterministic local setup.

### 1. Clone and Configure

```bash
git clone https://github.com/agustindiazcano/agentic-mcp-engine.git
cd agentic-mcp-engine
cp .env.example .env
```

Edit `.env` and fill in the required values. See the Environment Variables section below.

### 2. Start the Infrastructure

```bash
docker compose up -d postgres rabbitmq
```

### 3. Apply Database Migrations

```bash
alembic upgrade head
```

### 4. Start the MCP Server

```bash
python -m src.mcp_server.mcp_server
```

### 5. Start the Worker

```bash
python -m src.worker.worker
```

### 6. Start the API Gateway

```bash
uvicorn src.api.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `RABBITMQ_URL` | Yes | RabbitMQ AMQP connection string |
| `LLM_PROVIDER` | Yes | Active provider: `gemini`, `groq`, or `bedrock` |
| `GEMINI_API_KEY` | Conditional | Required when `LLM_PROVIDER=gemini` |
| `GROQ_API_KEY` | Conditional | Required when `LLM_PROVIDER=groq` |
| `LANGFUSE_SECRET_KEY` | No | Langfuse telemetry secret key |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse telemetry public key |
| `MCP_SERVER_URL` | Yes | URL of the running MCP server |
| `MAX_LLM_RETRIES` | No | Maximum LLM retry count (default: 3) |
| `IDEMPOTENCY_TTL_SECONDS` | No | Idempotency record TTL in seconds (default: 86400) |
| `EXPERT_SYSTEM_CONFIDENCE_THRESHOLD` | No | [Phase 2] Minimum belief degree required for auto-approval (default: 0.85) |
| `KALMAN_ALERT_SIGMA` | No | [Phase 3] Standard deviations from estimated state that trigger a drift alert (default: 2.0) |

---

## Running Tests

```bash
# Full test suite
pytest tests/ -v --tb=short

# Unit tests only (no infrastructure required)
pytest tests/unit/ -v

# Integration tests (requires Docker infrastructure)
pytest tests/integration/ -v

# Phase 2 confidence layer tests
pytest tests/unit/confidence/ -v
```

---

## Linting and Type Checking

```bash
ruff check src/
mypy src/ --strict
```

---

## Architecture Decision Records

### Why RabbitMQ over Kafka?

This engine targets transactional workloads (claims, refunds) where per-message acknowledgment, dead-letter routing, and low-latency delivery matter more than high-throughput log streaming. RabbitMQ's AMQP protocol gives fine-grained ACK/NACK control that maps directly to the idempotency and retry contract.

### Why the `src/` Layout?

With application code split across `app/`, `mcp_server/`, `worker/`, `confidence/`, and `observability/` directly at the repo root, Python import resolution depends on the current working directory — `worker.py` importing `confidence.fuzzy_layer` works when launched one way and fails with `ModuleNotFoundError` when launched another, and behaves differently again inside Docker. Nesting everything under `src/` makes every internal import absolute and resolves identically in local runs, tests, and containers, at the cost of one extra path segment.

### Why HTTP/SSE for MCP Transport, Not `stdio`?

The MCP Python SDK supports both. `stdio` is lighter-weight but requires the client to spawn the server as a child process, collapsing the worker and the MCP server into a single process. This project deliberately keeps them as independent services connected over HTTP/SSE (`MCP_SERVER_URL`) instead: it preserves independent deploys, independent scaling, and the ability for more than one worker to share a single MCP server — the distributed-systems boundary this project exists to demonstrate. `stdio` remains a reasonable choice for a single-process CLI tool; it is not the right fit here.

### Why MCP over Direct Function Calling?

The MCP server acts as a hard boundary between the LLM's reasoning space and the system's write paths. Even if the LLM hallucinates a tool invocation, the MCP server validates inputs, enforces authorization, and logs every call. This is not achievable with raw function calling.

### Why pgvector over a Dedicated Vector DB?

Embedding vectors live in the same PostgreSQL instance as transaction data. This allows atomic queries that join semantic search results with live business state in a single transaction, which no separate vector database can provide without a distributed join.

### Why a Rule-Based Expert System Alongside the LLM-Judge? (Phase 2)

The LLM-judge is a strong general-purpose guardrail, but it is itself a probabilistic model — its verdict is not fully traceable to a specific cause, and it inherits the sampling variance of its underlying model. For the two highest-risk tools (`execute_refund`, `validate_fraud_score`), the system adds a second, deterministic gate: a rule base with explicit, human-authored conditions and belief degrees. This does not claim to make the whole system "explainable" — the LLM generation step remains a black box — but it does make the specific approval decision for financial actions independently auditable, which the LLM-judge alone cannot guarantee.

### Why Kalman Filtering for Observability, Not a Drift-Detection Classifier? (Phase 3)

A dedicated ML drift-detection model would need its own training data, its own maintenance, and would itself be another opaque component to monitor. A Kalman filter, in contrast, is a small, well-understood state estimator with two parameters (process and measurement noise) applied directly to the quality metrics the system already produces. It favors the smaller, more transparent mechanism that solves the specific problem (distinguishing sustained drift from request-level noise) over a heavier model that would solve a broader, unneeded problem.

---

## Author

Agustin Diaz-Cano, MS Candidate

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.