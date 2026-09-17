#!/usr/bin/env python3
"""
safety_guard.py

PreToolUse hook: gates destructive or high-risk tool calls before the agent
executes them. Reads a JSON payload from stdin and writes a JSON decision
to stdout.

Decision values:
  allow      - proceed automatically
  ask        - prompt the user once (respects "Always Allow" cache)
  force_ask  - always prompt the user, even if previously cached
  deny       - hard-block, never execute

This script has NO external dependencies and runs on any Python 3.11+
installation without installing packages.
"""

import json
import re
import sys

# ---------------------------------------------------------------------------
# Patterns that indicate destructive intent in a shell command
# ---------------------------------------------------------------------------
DESTRUCTIVE_PATTERNS: list[tuple[str, str]] = [
    # SQL without WHERE clause
    (r"(?i)\b(DELETE|UPDATE)\b(?!.*\bWHERE\b)", "Destructive SQL without WHERE clause"),
    # Database drop operations
    (r"(?i)\bDROP\s+(TABLE|COLUMN|DATABASE|SCHEMA|INDEX)\b", "Schema-dropping SQL"),
    # Alembic downgrade
    (r"alembic\s+downgrade", "Alembic downgrade (potential data loss)"),
    # rm -rf style wipes
    (r"rm\s+(-rf?|--recursive)\s+/", "Recursive file deletion from root"),
    # Force-push to protected branches
    (r"git\s+push.*--force", "Force push to remote"),
    # Direct .env writes
    (r"(echo|printf|Set-Content|Out-File).*\.(env|secrets)", "Writing to secrets file"),
    # Dropping pgvector or public schema
    (r"(?i)DROP\s+EXTENSION\s+pgvector", "Dropping pgvector extension"),
]

# ---------------------------------------------------------------------------
# File paths that require explicit user approval before modification
# ---------------------------------------------------------------------------
PROTECTED_FILE_PATTERNS: list[tuple[str, str]] = [
    (r"alembic/versions/.*\.py", "Alembic migration file"),
    (r"worker\.py", "Worker ACK/NACK logic"),
    (r"mcp_server\.py", "MCP tool contract"),
    (r"\.env(\.\w+)?$", "Environment/secrets file"),
    (r"docker-compose.*\.yml", "Container orchestration file"),
]


def check_command(command_line: str) -> tuple[str, str]:
    """Return (decision, reason) for a shell command."""
    for pattern, label in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, command_line):
            return "force_ask", f"Potentially destructive operation detected: {label}. Review carefully before allowing."
    return "allow", ""


def check_file_write(target_file: str) -> tuple[str, str]:
    """Return (decision, reason) for a file write operation."""
    for pattern, label in PROTECTED_FILE_PATTERNS:
        if re.search(pattern, target_file):
            return "ask", f"Protected file targeted: {label}. Confirm this change is intentional."
    return "allow", ""


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Cannot parse payload; allow and let the agent handle it
        print(json.dumps({"decision": "allow"}))
        return

    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args", {})

    decision = "allow"
    reason = ""

    if tool_name == "run_command":
        command_line = args.get("CommandLine", "")
        decision, reason = check_command(command_line)

    elif tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
        target_file = args.get("TargetFile", "")
        decision, reason = check_file_write(target_file)

    output: dict = {"decision": decision}
    if reason:
        output["reason"] = reason

    print(json.dumps(output))


if __name__ == "__main__":
    main()
