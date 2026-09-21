---
name: tests
description: Runs the full local validation suite (lint, types, tests) before committing.
---

# `tests` Skill

Use this skill when the user asks to run tests, validate code, or use `/tests`.
This mirrors CLAUDE.md Section 11's "before opening a PR" checklist.

1. Lint and type-check:
   - `ruff check src/ tests/`
   - `mypy src/ --strict` (not `--ignore-missing-imports` — CLAUDE.md Section 4 requires strict mode)
2. Unit tests (no infrastructure required):
   - `pytest tests/unit/ -v`
3. If Docker infrastructure is running (`docker compose up -d postgres rabbitmq`, or the full Phase 1.C stack), also run integration tests:
   - `pytest tests/integration/ -v`

If any step fails, stop and fix it (or tell the user what failed) before
proceeding to `commit`, `ship`, or a PR — don't paper over a failure to get
to green.
