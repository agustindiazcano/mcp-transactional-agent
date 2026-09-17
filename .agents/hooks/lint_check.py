#!/usr/bin/env python3
"""
lint_check.py

PostToolUse hook: runs ruff and mypy after the agent writes or modifies a
Python file, then injects the results as a structured report back into the
agent's context.

Reads a JSON payload from stdin. Writes an empty JSON object {} to stdout
(PostToolUse hooks do not return decisions, only side effects).

Linting is only performed when the tool that just ran was write_to_file,
replace_file_content, or multi_replace_file_content, and the modified file
has a .py extension.
"""

import json
import subprocess
import sys


def run(cmd: list[str], cwd: str) -> tuple[int, str]:
    """Execute a subprocess and return (returncode, combined output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return -1, f"Command not found: {cmd[0]}"


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("{}")
        return

    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args", {})
    target_file: str = args.get("TargetFile", "")

    write_tools = {"write_to_file", "replace_file_content", "multi_replace_file_content"}

    if tool_name not in write_tools or not target_file.endswith(".py"):
        print("{}")
        return

    workspaces = payload.get("workspacePaths", [])
    cwd = workspaces[0] if workspaces else "."

    ruff_code, ruff_out = run(["ruff", "check", "--output-format=concise", target_file], cwd)
    mypy_code, mypy_out = run(["mypy", "--ignore-missing-imports", target_file], cwd)

    report_lines = [f"Lint report for {target_file}"]
    if ruff_out:
        report_lines.append(f"ruff: {ruff_out}")
    else:
        report_lines.append("ruff: clean")
    if mypy_out:
        report_lines.append(f"mypy: {mypy_out}")
    else:
        report_lines.append("mypy: clean")

    # Write a human-readable report file next to the modified file
    report_path = target_file + ".lint_report.txt"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
    except OSError:
        pass

    print("{}")


if __name__ == "__main__":
    main()
