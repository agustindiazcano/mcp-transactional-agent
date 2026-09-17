# Persistent Rules: agentic-mcp-engine

These rules apply to every interaction in this workspace. They extend the
directives in GEMINI.md and CLAUDE.md and are enforced at all times.

## Code Quality Rules

1. Do not generate code without type annotations on any public function or class.
2. Do not generate async functions that use blocking I/O (e.g., `time.sleep`, `requests.get`). Use `asyncio.sleep` and `httpx.AsyncClient` instead.
3. Do not use `from module import *`. Always use explicit imports.
4. Do not generate code that catches `Exception` as a bare catch-all without re-raising or logging the specific error.
5. Do not leave TODO comments in generated code. Either implement the feature or explicitly ask the user to decide.

## Architecture Enforcement Rules

6. If asked to write logic that reads from or writes to the database inside `app/routers/` or `app/agents/`, refuse and explain the correct layer to use instead.
7. If asked to put a `requests` or `httpx` call inside `app/repositories/`, refuse and explain that repositories are for database access only. External HTTP calls belong in `app/services/`.
8. If the user asks to hardcode an API key, connection string, or any secret value in source code, refuse and generate the equivalent `pydantic-settings` configuration pattern instead.

## Safety Rules

9. Before executing any command that modifies the database (Alembic upgrade, direct SQL), confirm the current Alembic revision and the target revision with the user.
10. Before deleting or moving any file that contains database models, router definitions, or MCP tool registrations, explicitly list what will be affected and ask for confirmation.
11. Do not generate shell scripts that use `rm -rf` or equivalent destructive commands without a dry-run option.

## Communication Rules

12. Speak in English only.
13. Do not use decorative icons in responses.
14. When explaining a refusal (rules 6-11), always include a concrete alternative that achieves the user's goal the correct way.
15. When proposing a multi-step implementation, number the steps and state which development phase (1-5 from the project context) each step belongs to.
