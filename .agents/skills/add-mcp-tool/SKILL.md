---
name: add-mcp-tool
description: >-
  Use this skill when the user asks to add, modify, or remove a tool from the
  MCP server (mcp_server.py). Adding or renaming tools is a breaking change
  for live agents. This skill enforces the safe procedure for evolving the
  MCP tool contract.
---

# MCP Tool Evolution Runbook

Adding, modifying, or removing an MCP tool changes the contract that the LLM
agent relies on. Follow this procedure to avoid breaking live workers.

## Step 1 - Classify the Change

| Change Type | Risk | Required Action |
|---|---|---|
| Add a new tool | Low | Standard implementation |
| Modify a tool's input schema (additive) | Medium | Version the tool name |
| Modify a tool's output schema | High | Confirm with user, update agent prompts |
| Rename a tool | High | Confirm with user, coordinate worker deployment |
| Remove a tool | Critical | Hard block - requires explicit user approval |

For HIGH or CRITICAL changes, stop here and confirm with the user before proceeding.

## Step 2 - Implement the New Tool

Create the tool function in `mcp_server/tools/<tool_name>.py`:

```python
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
import structlog

log = structlog.get_logger()


class GetUserHistoryInput(BaseModel):
    user_id: str
    limit: int = 10


async def get_user_history(params: GetUserHistoryInput) -> dict:
    """
    Retrieve recent transaction history for a user.

    This tool may only read data. It must never write to the database.

    Args:
        params: GetUserHistoryInput containing user_id and optional limit.

    Returns:
        A dict with a 'transactions' key containing a list of records.
    """
    log.info("mcp_tool.get_user_history.called", user_id=params.user_id)
    # ... implementation
```

Rules:
- Tool functions must be async.
- Tools must never write to the database unless they are explicitly flagged as write tools.
- All input must be validated with a Pydantic model.
- Log every tool call with structlog at INFO level.
- Return a plain dict (JSON-serializable).

## Step 3 - Register the Tool

In `mcp_server/mcp_server.py`, register using the MCP SDK:

```python
from mcp_server.tools.get_user_history import get_user_history, GetUserHistoryInput

mcp = FastMCP("agentic-mcp-engine")

@mcp.tool()
async def get_user_history_tool(user_id: str, limit: int = 10) -> dict:
    return await get_user_history(GetUserHistoryInput(user_id=user_id, limit=limit))
```

## Step 4 - Write Integration Tests

Create `tests/integration/test_mcp_<tool_name>.py`:

```python
import pytest
from mcp_server.tools.<tool_name> import <ToolInput>, <tool_function>


@pytest.mark.asyncio
async def test_<tool_name>_happy_path():
    result = await <tool_function>(<ToolInput>(...))
    assert "expected_key" in result


@pytest.mark.asyncio
async def test_<tool_name>_invalid_input():
    with pytest.raises(ValidationError):
        <ToolInput>(invalid_field="bad_value")
```

## Step 5 - Update the System Prompt

If the tool is new, the worker's LLM system prompt must be updated to tell
the agent about the new tool and when to use it. Update:
`app/agents/system_prompt.py`.

## Step 6 - Validate

```bash
pytest tests/integration/test_mcp_<tool_name>.py -v
ruff check mcp_server/
mypy mcp_server/ --ignore-missing-imports
```

## Step 7 - Document

Update `mcp_server/README.md` with:
- Tool name and purpose.
- Input schema (fields, types, defaults).
- Output schema (fields, types).
- Any side effects (write operations).
