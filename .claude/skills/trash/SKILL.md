---
name: trash
description: >-
  Use this skill when the user types "/trash" or asks to discard, trash, or
  restore all uncommitted changes because they don't like the current
  progress. Resets the working tree to the last commit.
---

# Trash / Discard Changes Runbook

Discards all uncommitted work (tracked and untracked). This is destructive
and irreversible for anything not committed — follow the confirmation step,
don't skip it just because a skill is invoking the commands.

## Step 1 - Confirm Intent

If the user explicitly typed `/trash`, that is the confirmation — proceed.
If they were vague ("I don't like this, undo it"), briefly confirm they want
to lose all uncommitted changes, not just the last edit.

## Step 2 - Show What Will Be Lost

Run `git status` first and show the user what's about to be discarded —
don't reset blind.

## Step 3 - Execute

```bash
git restore .
git clean -fd
```

## Step 4 - Report Status

Confirm the workspace is clean. Do not attempt to recover or re-implement the
discarded code — just acknowledge the reset.
