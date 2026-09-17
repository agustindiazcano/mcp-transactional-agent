---
name: commit
description: Stages changes, generates a commit message using Conventional Commits, and commits.
---

# `commit` Skill

Use this skill when the user asks to commit changes or use `/commit`.

1. Check the current git status: `git status`
2. Review the changes using `git diff` to understand what was modified.
3. Stage the files: `git add .`
4. Generate a commit message following the **Conventional Commits** standard (e.g., `feat: ...`, `fix: ...`, `chore: ...`). Keep the message descriptive but concise.
5. Commit the changes: `git commit -m "<message>"`

Do not push unless explicitly requested.
