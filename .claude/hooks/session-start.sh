#!/usr/bin/env bash
# SessionStart hook: delegates to session_start.py (see .claude/settings.json).
exec python "$CLAUDE_PROJECT_DIR/.claude/hooks/session_start.py"
