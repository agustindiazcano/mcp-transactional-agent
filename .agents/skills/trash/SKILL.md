---
name: trash
description: >-
  Use this skill when the user types "/trash" or asks to discard, trash, or restore
  all uncommitted changes because they don't like the current progress.
  It executes a clean reset to the last commit to wipe out the current work.
---

# Trash / Discard Changes Runbook

When the user wants to discard their current uncommitted work (often invoked via `/trash`), follow this procedure to restore the repository to a clean state.

## Step 1 - Confirm Intent (If not explicitly clear)

If the user just types `/trash`, you can assume they want to discard everything. If they are vague, confirm briefly that they want to lose all uncommitted changes.

## Step 2 - Execute Git Restore and Clean

Run the following commands to restore tracked files and remove untracked files (new files created during the failed feature attempt).

```bash
# Discard changes in tracked files
git restore .

# Remove untracked files and directories
git clean -fd
```

## Step 3 - Report Status

Confirm to the user that the workspace is now clean and all uncommitted changes have been successfully removed. Do not attempt to fix or modify the discarded code. Just acknowledge the reset.
