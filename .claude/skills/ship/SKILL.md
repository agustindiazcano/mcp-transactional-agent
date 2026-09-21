---
name: ship
description: Runs the full local validation suite and, if it passes, commits and pushes.
---

# `ship` Skill

Use this skill when the user asks to "ship", "test and ship", or uses `/ship`.

1. **Guard**: check the current branch (`git branch --show-current`). If it's
   `main`, stop — CLAUDE.md Section 11 forbids committing directly to `main`;
   tell the user to create a feature branch first.
2. **Validation**: follow the `tests` skill exactly (ruff, mypy --strict, pytest).
3. If validation fails, stop. Do not commit or push — fix the errors or tell the user.
4. **Commit**: if validation passes, follow the `commit` skill (stage named files, Conventional Commits message).
5. **Push**: `git push` (or `git push -u origin <branch>` if the branch has no upstream yet).
