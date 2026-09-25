#!/usr/bin/env python3
"""
session_start.py

SessionStart hook: injects LASTCONTEXT.md and PENDING.md into context at the
start of every session, so Claude picks up current state and the open
roadmap without being told to read them first.

Matcher (see .claude/settings.json): SessionStart (no matcher, fires always)

No external dependencies; runs on any Python 3.11+.
"""

import json
import os

FILES = ("LASTCONTEXT.md", "PENDING.md")


def main() -> None:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    sections = []

    for name in FILES:
        path = os.path.join(project_dir, name)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                sections.append(f"## {name}\n\n{content}")

    if not sections:
        return

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(sections),
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
