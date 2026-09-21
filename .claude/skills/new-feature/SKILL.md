---
name: new-feature
description: >-
  Use this skill when the user asks to implement a new feature, endpoint,
  service, repository, or agent component in agentic-mcp-engine. Enforces
  layer isolation and CLAUDE.md's phase model.
---

# New Feature Implementation Runbook

Follow this sequence. Do not skip steps or merge them. This project uses strict
Red-Green-Refactor TDD (CLAUDE.md Section 6b) — write the failing test before
the implementation at every layer below, not just once at the end.

## Step 1 - Clarify Scope

Before writing code, answer:

1. Which phase does this belong to? (See CLAUDE.md Section 2: Phase 1 core engine, 1.B security boundary, 1.C containerization, 1.D RAG, 2 confidence layer, 3 drift detection, 4 dashboard, 5 ML comparison, 6 cloud migration.)
2. Which layers are involved? (router, service, repository, agent, MCP tool, worker)
3. Does this require a database migration? → use the `db-migration` skill.
4. Does this expose a new or modified MCP tool? → use the `add-mcp-tool` skill.
5. Does this interact with the LLM directly?

If any answer is unclear, ask the user before proceeding.

## Step 2 - Models and Migrations (if applicable)

- Define or update SQLAlchemy models in `src/core/models.py`.
- Use the `db-migration` skill to generate and review the Alembic migration.

## Step 3 - Repository Layer

- Add or update the relevant file in `src/core/repositories/` (currently scaffolded but empty — this may be the first real file in that directory; follow CLAUDE.md's Separation of Concerns directive, not an existing example).
- All methods must be `async` and accept an `AsyncSession`.
- Write the failing unit test in `tests/unit/` first.
- Run: `pytest tests/unit/ -v`.

## Step 4 - Service Layer

- Add or update the relevant file in `src/core/services/` (also currently empty scaffolding).
- Services call repositories; they must never import SQLAlchemy models directly, and must never make outbound HTTP calls — that belongs in `src/agents/` (LLM calls) or a dedicated client module, not the service layer.
- Write unit tests with mocked repositories.

## Step 5 - Router Layer (Ingestion only)

- Add or update routes in `src/api/routers/`.
- Use Pydantic models for all request/response bodies.
- Endpoints that trigger async work must return HTTP `202 Accepted` with a `request_id`, matching the existing `src/api/main.py` ingestion pattern.
- No business logic in router functions.

## Step 6 - MCP Tool (if applicable)

Use the `add-mcp-tool` skill — it has the safe procedure for evolving the tool contract without breaking live agents.

## Step 7 - Worker Integration (if applicable)

- Changes to `src/worker/worker.py` touch the idempotency check and the ACK/NACK sequence — both are flagged in CLAUDE.md Section 8 (pause and confirm before modifying ACK/NACK logic).
- The idempotency check (`request_id` lookup, pessimistic `SELECT ... FOR UPDATE`) must remain the first operation after message consumption.
- If the change affects stale-transaction recovery, also review `src/worker/recovery_sweeper.py` — it must never be imported from `worker.py` (they run as independent processes; see the module's own docstring).

## Step 8 - Guardrails (if an LLM decision is involved)

- Route the LLM output through `src/agents/judge.py` (Double Judge) before any write operation.
- If either judge returns `REJECT`, or the base judges disagree, the escalation path is: self-correction retry (up to `MAX_LLM_RETRIES`) → Supreme Court cascade judge → `PENDING_HUMAN_REVIEW` (CLAUDE.md Section 10).
- For `execute_refund` / `validate_fraud_score`, once Phase 2 is live, the rule-base verdict is also required — either signal alone routes to `PENDING_HUMAN_REVIEW`.

## Step 9 - Tests and Validation

```bash
pytest tests/ -v --tb=short
ruff check src/
mypy src/ --strict
```

## Step 10 - Documentation

- Update README.md with any new environment variables (also add them to CLAUDE.md Section 9 — the two must stay in sync).
- Document new endpoints and MCP tools where the existing README sections cover them.
