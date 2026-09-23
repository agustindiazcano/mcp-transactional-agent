#!/usr/bin/env python3
"""
lint_check.py

PostToolUse hook: after Claude Code writes or edits a .py file, runs ruff and
mypy --strict against it and feeds the result back into Claude's context via
hookSpecificOutput.additionalContext (CLAUDE.md requires mypy --strict, not
--ignore-missing-imports).

Matcher (see .claude/settings.json): Write|Edit

The tools run from the project's virtualenv, not whatever is on PATH: a global
mypy can't see the project's dependencies and reports every third-party import
as missing, which reaches the agent as noise on every edit. Like CI (`mypy
src`), only files under src/ are type-checked; ruff checks every Python file.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def project_python(cwd: str) -> str:
    """The interpreter of the active or project virtualenv, else this one."""
    candidates = [os.environ.get("VIRTUAL_ENV", ""), str(Path(cwd) / ".venv"),
                  str(Path(cwd) / "venv")]
    for venv in filter(None, candidates):
        for relative in ("Scripts/python.exe", "bin/python"):
            python = Path(venv) / relative
            if python.is_file():
                return str(python)
    return sys.executable


def should_type_check(target_file: str, cwd: str) -> bool:
    """True for files under src/, the scope CI type-checks."""
    path = Path(target_file.replace("\\", "/"))
    if path.is_absolute():
        try:
            path = path.relative_to(Path(cwd).resolve())
        except ValueError:
            return False
    return path.parts[:1] == ("src",)


def run(cmd: list[str], cwd: str) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=60, check=False
        )
        return (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return f"({cmd[0]} not found on PATH — skipped)"
    except subprocess.TimeoutExpired:
        return f"({cmd[0]} timed out after 60s)"


def _is_clean(output: str) -> bool:
    return not output or output.startswith(("All checks passed", "Success: no issues"))


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

    python = project_python(cwd)
    ruff_out = run([python, "-m", "ruff", "check", "--output-format=concise", target_file], cwd)
    mypy_out = ""
    if should_type_check(target_file, cwd):
        mypy_out = run([python, "-m", "mypy", "--strict", target_file], cwd)

    lines = [f"Lint report for {target_file}:"]
    lines.append(f"ruff: {ruff_out or 'clean'}")
    lines.append(f"mypy --strict: {mypy_out or 'clean'}")

    if _is_clean(ruff_out) and _is_clean(mypy_out):
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
