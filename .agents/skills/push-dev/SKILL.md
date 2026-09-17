---
name: push-dev
description: Commits and pushes to GitHub immediately without running any tests or validations.
---

# `push-dev` Skill

Use this skill when the user explicitly asks to "push-dev", "/push-dev", or bypass tests and push immediately.

1. Check the current git status: `git status`
2. Stage the files: `git add .`
3. Generate a quick commit message following Conventional Commits, or ask the user if the intent is not clear.
4. Commit the changes: `git commit -m "<message>"`
5. Push to the current branch: `git push`

**Warning**: This bypasses all safety nets (ruff, mypy, pytest). Only use when the user asks for `/push-dev`.
