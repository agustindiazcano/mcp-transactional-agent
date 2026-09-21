#!/usr/bin/env python3
"""
safety_guard.py

PreToolUse hook: gates destructive or high-risk tool calls before Claude Code
executes them. Reads the Claude Code hook payload from stdin and writes a
hookSpecificOutput permission decision to stdout.

Matcher (see .claude/settings.json): Bash|PowerShell|Write|Edit

Decisions:
  allow  - proceed automatically (script prints nothing / {})
  ask    - prompt the user for confirmation
  deny   - hard-block, tool never runs

No external dependencies; runs on any Python 3.11+.
"""

import json
import re
import sys

# ---------------------------------------------------------------------------
# Hard-blocked commands: never executed, no "Always Allow" override possible.
# PENDING.md is the user's personal working roadmap. It must never be deleted
# or emptied by any tool call, regardless of git-tracked status — see
# CLAUDE.md Section 8.
# ---------------------------------------------------------------------------
DENY_COMMAND_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\b(rm|del|erase)\b[^|&;\n]*PENDING\.md", "Deleting PENDING.md is not allowed — it must never be removed."),
    (r"(?i)Remove-Item[^|&;\n]*PENDING\.md", "Deleting PENDING.md is not allowed — it must never be removed."),
    (r"(?i)git\s+rm[^|&;\n]*PENDING\.md", "Deleting PENDING.md (even via git rm) is not allowed."),
    (r"(?<!>)>\s*PENDING\.md\b", "Truncating/overwriting PENDING.md via shell redirection is not allowed."),
]

# ---------------------------------------------------------------------------
# Patterns that indicate destructive intent in a shell command (Bash or
# PowerShell tool_input.command).
# ---------------------------------------------------------------------------
DESTRUCTIVE_COMMAND_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\b(DELETE|UPDATE)\b(?!.*\bWHERE\b)", "Destructive SQL without a WHERE clause"),
    (r"(?i)\bDROP\s+(TABLE|COLUMN|DATABASE|SCHEMA|INDEX)\b", "Schema-dropping SQL"),
    (r"(?i)DROP\s+EXTENSION\s+(pgvector|vector)", "Dropping the pgvector extension"),
    (r"alembic\s+downgrade", "Alembic downgrade (potential data loss)"),
    (r"rm\s+(-rf?|--recursive)\s+/", "Recursive deletion from filesystem root"),
    (r"Remove-Item.*-Recurse.*-Force", "Recursive forced deletion (PowerShell)"),
    (r"git\s+push[^|&;]*--force", "Force push to a remote"),
    (r"git\s+reset\s+--hard", "Hard reset (discards uncommitted work)"),
    (r"git\s+clean\s+.*-[a-z]*f", "git clean -f (permanently deletes untracked files)"),
    (r"git\s+restore\s+\.", "git restore . (discards all uncommitted tracked changes)"),
    (r"(echo|printf|Set-Content|Out-File|Add-Content)[^|&;]*\.(env|secrets)\b", "Writing to a secrets file"),
    (r"docker\s+compose\s+down\s+.*-v\b", "docker compose down -v (deletes named volumes, i.e. the local database)"),
]

# ---------------------------------------------------------------------------
# File paths that require explicit user approval before modification.
# Mirrors CLAUDE.md Section 8 (Safety and Review Boundaries).
# ---------------------------------------------------------------------------
PROTECTED_FILE_PATTERNS: list[tuple[str, str]] = [
    (r"alembic[/\\]versions[/\\].*\.py$", "Alembic migration file (CLAUDE.md #8: dropping a column/table needs confirmation)"),
    (r"src[/\\]worker[/\\]worker\.py$", "Worker ACK/NACK logic (CLAUDE.md #8)"),
    (r"src[/\\]mcp_server[/\\]mcp_server\.py$", "MCP tool contract — renaming/removing a tool breaks live agents (CLAUDE.md #8)"),
    (r"src[/\\]confidence[/\\]rules[/\\]", "Belief rule base — do not lower an execute_refund/validate_fraud_score threshold without confirming (CLAUDE.md #8)"),
    (r"(^|[/\\])\.env(\.\w+)?$", "Environment/secrets file (CLAUDE.md #8)"),
    (r"docker-compose.*\.ya?ml$", "Container orchestration file"),
]


def check_command(command_line: str) -> tuple[str, str]:
    for pattern, label in DENY_COMMAND_PATTERNS:
        if re.search(pattern, command_line):
            return "deny", label
    for pattern, label in DESTRUCTIVE_COMMAND_PATTERNS:
        if re.search(pattern, command_line):
            return "ask", f"Potentially destructive operation: {label}. Confirm before allowing."
    return "allow", ""


def check_file_write(target_file: str) -> tuple[str, str]:
    for pattern, label in PROTECTED_FILE_PATTERNS:
        if re.search(pattern, target_file):
            return "ask", f"Protected file targeted: {label}."
    return "allow", ""


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("{}")
        return

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    decision = "allow"
    reason = ""

    if tool_name in ("Bash", "PowerShell"):
        command_line = tool_input.get("command", "")
        decision, reason = check_command(command_line)
    elif tool_name in ("Write", "Edit"):
        target_file = tool_input.get("file_path", "")
        decision, reason = check_file_write(target_file)

    if decision == "allow":
        print("{}")
        return

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
