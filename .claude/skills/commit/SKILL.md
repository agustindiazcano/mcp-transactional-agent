---
name: commit
description: Stages changes, generates a Conventional Commits message, and commits.
---

# `commit` Skill

Use this skill when the user asks to commit changes or use `/commit`.

1. Check the current git status: `git status`.
2. Review the changes: `git diff` (unstaged) and `git diff --staged` (already staged).
3. Stage specific files by name — not `git add .` or `git add -A` — so an unrelated stray file (`.env`, a `*.lint_report.txt`, a scratch file) never rides along. If `git status` shows something unexpected, ask before staging it.
4. Generate a commit message in **Conventional Commits** format (`feat: ...`, `fix: ...`, `chore: ...`, `docs: ...`), matching this repo's existing log style (`git log --oneline -10`). Focus on *why*, not a restatement of the diff.
5. Commit: `git commit -m "<message>"`.

Do not push unless explicitly requested — see the `ship` and `push-dev` skills for that. Never commit directly to `main` (CLAUDE.md Section 11) — if the current branch is `main`, stop and ask.
