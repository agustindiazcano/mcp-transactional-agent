---
name: push-dev
description: Commits and pushes immediately without running lint/type/test validation.
---

# `push-dev` Skill

Use this skill when the user explicitly asks to "push-dev", uses `/push-dev`,
or asks to bypass validation and push immediately. Only for work-in-progress
feature branches.

1. Check the current branch (`git branch --show-current`). If it's `main`, stop — CLAUDE.md Section 11 forbids committing directly to `main`.
2. `git status`.
3. Stage specific files by name (not `git add .`/`-A`) — review what `git status` shows before staging.
4. Generate a quick Conventional Commits message, or ask if intent is unclear.
5. `git commit -m "<message>"`.
6. `git push` (or `git push -u origin <branch>` if no upstream yet).

**Warning**: this bypasses ruff, mypy, and pytest. Only use it when the user
explicitly asks for `/push-dev` or an unvalidated push.
