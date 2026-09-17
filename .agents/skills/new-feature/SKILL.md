---
name: new-feature
description: >-
  Use this skill when the user asks to implement a new feature, endpoint,
  service, repository, or agent component in the agentic-mcp-engine project.
  It enforces the sequential development phase order and layer isolation rules.
---

# New Feature Implementation Runbook

Follow this sequence exactly. Do not skip phases or merge them.

## Phase 1 - Clarify Scope

Before writing a single line of code, answer these questions:

1. Which development phase does this feature belong to? (Infrastructure, Ingestion, MCP Server, Worker, Guardrails)
2. Which layers are involved? (router, service, repository, agent)
3. Does this feature require a database migration?
4. Does this feature expose a new MCP tool, or modify an existing one?
5. Does this feature interact with the LLM directly?

If any answer is unclear, ask the user before proceeding.

## Phase 2 - Models and Migrations (if applicable)

- Define or update SQLAlchemy models in `app/models.py`.
- Generate an Alembic migration: `alembic revision --autogenerate -m "<description>"`.
- Review the generated migration file before applying it.
- Apply: `alembic upgrade head`.

Validation: confirm that `alembic current` shows the expected revision head.

## Phase 3 - Repository Layer

- Create or update the relevant file in `app/repositories/`.
- All methods must be async and accept a `db: AsyncSession` argument.
- Write at least one unit test in `tests/unit/` before implementing the method body (TDD).
- Run tests: `pytest tests/unit/ -v`.

## Phase 4 - Service Layer

- Create or update the relevant file in `app/services/`.
- Services must only call repositories; they must not import SQLAlchemy models directly.
- All side effects (RabbitMQ publish, external HTTP) go here, not in the router.
- Write unit tests with mocked repositories.

## Phase 5 - Router Layer (Ingestion only)

- Add or update routes in `app/routers/`.
- Use Pydantic models for all request and response bodies.
- Endpoints that trigger async work must return HTTP 202 Accepted with a `request_id`.
- Never put business logic in a router function.

## Phase 6 - MCP Tool (if applicable)

- Add the new tool function in `mcp_server/tools/`.
- Register it in `mcp_server/mcp_server.py` using the MCP SDK decorator.
- Write an integration test that calls the tool through the MCP client.
- Document the tool's input schema and output schema in a docstring.

## Phase 7 - Worker Integration (if applicable)

- If the feature requires worker changes, update `worker/worker.py`.
- The idempotency check must remain the first operation after message consumption.
- Never remove or reorder the ACK/NACK sequence.

## Phase 8 - Guardrails (if LLM decision involved)

- Pass the LLM output through the judge function before any write operation.
- If judge returns REJECT, set transaction status to `PENDING_HUMAN_REVIEW`.
- Log the reject reason with `structlog` at WARNING level.

## Phase 9 - Tests and Validation

Run the full test suite before considering the feature done:

```
pytest tests/ -v --tb=short
```

Check for lint errors:

```
ruff check app/ mcp_server/ worker/
mypy app/ mcp_server/ worker/ --ignore-missing-imports
```

## Phase 10 - Documentation

- Update `README.md` with any new environment variables.
- Add the new endpoint to the API reference section if applicable.
- If a new MCP tool was added, document it in `mcp_server/README.md`.
