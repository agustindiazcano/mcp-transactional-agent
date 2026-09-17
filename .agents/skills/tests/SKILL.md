---
name: tests
description: Runs the full test suite and validation tools locally before committing.
---

# `tests` Skill

Use this skill when the user asks to run tests, validate code, or use `/tests`.

1. Run the formatting and linting checks:
   - `ruff check src/ tests/`
   - `mypy src/ --strict`
2. Run unit tests:
   - `pytest tests/unit/ -v`
3. If infrastructure is running (docker-compose), run integration tests:
   - `pytest tests/integration/ -v`

If any of these fail, STOP and fix them before proceeding or inform the user.
