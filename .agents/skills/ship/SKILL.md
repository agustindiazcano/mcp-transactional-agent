---
name: ship
description: Executes the full CI pipeline locally (tests, linting) and if successful, commits and pushes.
---

# `ship` Skill

Use this skill when the user asks to "ship", "tests and ship", or use `/ship`.

This is a composite skill. Execute the following sequence:

1. **Validation**: Follow the `tests` skill exactly (run `ruff`, `mypy`, and `pytest`).
2. If validation fails, STOP. Do not commit or push. Fix the errors or inform the user.
3. **Commit**: If validation passes, follow the `commit` skill exactly (stage and commit with Conventional Commits).
4. **Push**: Push to the current branch: `git push`.
