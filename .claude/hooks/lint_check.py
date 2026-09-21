#!/usr/bin/env python3
"""
lint_check.py

PostToolUse hook: after Claude Code writes or edits a .py file, runs ruff and
mypy --strict against it and feeds the result back into Claude's context via
hookSpecificOutput.additionalContext (CLAUDE.md requires mypy --strict, not
--ignore-missing-imports).

Matcher (see .claude/settings.json): Write|Edit
"""

import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: str) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=60)
        return (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return f"({cmd[0]} not found on PATH — skipped)"
    except subprocess.TimeoutExpired:
        return f"({cmd[0]} timed out after 60s)"


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("{}")
        return

    tool_input = payload.get("tool_input", {})
    target_file = tool_input.get("file_path", "")

    if not target_file.endswith(".py") or not Path(target_file).exists():
        print("{}")
        return

    cwd = payload.get("cwd") or "."

    ruff_out = run(["ruff", "check", "--output-format=concise", target_file], cwd)
    mypy_out = run(["mypy", "--strict", target_file], cwd)

    lines = [f"Lint report for {target_file}:"]
    lines.append(f"ruff: {ruff_out or 'clean'}")
    lines.append(f"mypy --strict: {mypy_out or 'clean'}")

    if not ruff_out and not mypy_out:
        # Nothing to report — stay silent, don't clutter context on every clean edit.
        print("{}")
        return

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(lines),
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
