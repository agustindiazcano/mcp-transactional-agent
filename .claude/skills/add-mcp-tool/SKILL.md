---
name: add-mcp-tool
description: >-
  Use this skill when the user asks to add, modify, or remove a tool from the
  MCP server (src/mcp_server/mcp_server.py). Adding or renaming tools is a
  breaking change for live agents. Enforces the safe procedure for evolving
  the MCP tool contract.
---

# MCP Tool Evolution Runbook

Adding, modifying, or removing an MCP tool changes the contract the LLM agent
relies on. Follow this procedure to avoid breaking live workers.

## Step 1 - Classify the Change

| Change Type | Risk | Required Action |
|---|---|---|
| Add a new tool | Low | Standard implementation |
| Modify a tool's input schema (additive) | Medium | Note the change in the tool docstring |
| Modify a tool's output schema | High | Confirm with user |
| Rename a tool | High | Confirm with user — flagged in CLAUDE.md Section 8 |
| Remove a tool | Critical | Hard block — CLAUDE.md Section 8 requires explicit user approval before removing/renaming an existing tool |

For High or Critical changes, stop and confirm with the user before proceeding.

## Step 2 - Implement the Tool

Today `src/mcp_server/mcp_server.py` is a single flat file: tools are plain
functions decorated with `@mcp.tool()` directly in that file (there is a
`src/mcp_server/tools/` directory scaffolded for when this grows, but nothing
lives there yet — don't invent a `tools/<name>.py` submodule pattern unless
the user asks to split the file up).

```python
@mcp.tool()
async def get_user_history(user_id: str, limit: int = 10) -> dict:
    """Retrieve recent transaction history for a user. Read-only."""
    log.info("mcp_tool.get_user_history.called", user_id=user_id)
    # delegate real data access to src/core/repositories/, not inline SQL here
    ...
```

Rules:
- If the tool does any I/O (DB, HTTP), it must be `async` (CLAUDE.md Section 6) — the current `execute_refund`/`validate_fraud_score` stubs are `def`, not `async def`, only because they don't do real I/O yet. A real implementation must not copy that.
- A write tool must go through `src/core/repositories/`, never raw SQL inline in the tool function.
- Validate all input with a Pydantic model with explicit business limits (e.g. a bounded refund amount) — this is the argument-validation half of the Phase 1.B security boundary (CLAUDE.md Section 5a-i), even before the auth/rate-limit half lands.
- Log every call with `structlog` (never `print()`).
- Return a plain, JSON-serializable dict.

## Step 3 - Once Phase 1.B Is Live: Update the Client Allowlist

Once `src/mcp_server/security/` exists, a new tool also needs an entry in
the server-side per-`client_id` allowlist, or no worker can call it even
though it's registered. Check whether that module exists yet before skipping
this step.

## Step 4 - Write Integration Tests

Create `tests/integration/test_mcp_<tool_name>.py`, calling the tool through
an MCP client against the running server (see `debug-worker`'s "Step 5" for
how to stand up a local message for end-to-end testing).

## Step 5 - Update the System Prompt

If the tool is new, the primary agent's prompt must be updated to tell it the
tool exists and when to use it (see `src/agents/` for where prompts live).

## Step 6 - Validate

```bash
pytest tests/integration/test_mcp_<tool_name>.py -v
ruff check src/mcp_server/
mypy src/mcp_server/ --strict
```
