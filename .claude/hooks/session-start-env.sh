#!/bin/bash
# SessionStart hook for Claude Code on the web.
#
# Brings up everything the local test suite needs that Docker Compose would
# normally provide, without Docker (no daemon is available in this
# container): PostgreSQL 16 + pgvector (dev + _test databases, migrated to
# head) and RabbitMQ, then installs the project with its dev extras so
# pytest/ruff/mypy run exactly as CLAUDE.md's TDD workflow (Section 6b)
# expects. Real LLM calls still need API keys added as environment secrets
# separately -- this script never touches those.
#
# Idempotent: safe to re-run (apt/pip installs are no-ops when already
# installed; DB/extension/user creation is guarded).
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# ── System packages: PostgreSQL 16 + pgvector, RabbitMQ ─────────────────────
if ! dpkg -s postgresql-16-pgvector >/dev/null 2>&1 || ! dpkg -s rabbitmq-server >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq postgresql-16-pgvector rabbitmq-server
fi

# ── PostgreSQL: start, set password, create dev + test DBs, enable pgvector ─
service postgresql start
for _ in $(seq 1 15); do
  pg_isready -q && break
  sleep 1
done

su postgres -c "psql -v ON_ERROR_STOP=1 -c \"ALTER USER postgres PASSWORD 'password';\""
su postgres -c "psql -v ON_ERROR_STOP=1 -tc \"SELECT 1 FROM pg_database WHERE datname='agentic_engine'\" | grep -q 1 \
  || psql -v ON_ERROR_STOP=1 -c 'CREATE DATABASE agentic_engine;'"
su postgres -c "psql -v ON_ERROR_STOP=1 -tc \"SELECT 1 FROM pg_database WHERE datname='agentic_engine_test'\" | grep -q 1 \
  || psql -v ON_ERROR_STOP=1 -c 'CREATE DATABASE agentic_engine_test;'"
su postgres -c "psql -v ON_ERROR_STOP=1 -d agentic_engine -c 'CREATE EXTENSION IF NOT EXISTS vector;'"
su postgres -c "psql -v ON_ERROR_STOP=1 -d agentic_engine_test -c 'CREATE EXTENSION IF NOT EXISTS vector;'"

# ── RabbitMQ: start if not already running ───────────────────────────────────
if ! rabbitmqctl status >/dev/null 2>&1; then
  (rabbitmq-server -detached)
  for _ in $(seq 1 15); do
    rabbitmqctl status >/dev/null 2>&1 && break
    sleep 1
  done
fi

# ── Python project + dev extras ──────────────────────────────────────────────
# --ignore-installed PyJWT: the OS ships a PyJWT with no RECORD file, which
# pip refuses to uninstall over; this project's PyJWT-consuming deps get
# their own copy instead.
python -m pip install -e ".[dev]" -q --ignore-installed PyJWT

# ── Local .env (gitignored) ──────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  sed -i 's|^TEST_DATABASE_URL=.*|TEST_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/agentic_engine_test|' .env
  # .env.example's LangSmith block points at a placeholder key; leaving it
  # enabled makes every test run try (and fail) an outbound call. This
  # project's real tracing is Langfuse (src/core/tracing.py), already off
  # by default via LANGFUSE_TRACING_ENABLED.
  sed -i 's|^LANGCHAIN_TRACING_V2=true|LANGCHAIN_TRACING_V2=false|' .env
fi

# ── Migrate both databases to head ───────────────────────────────────────────
DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/agentic_engine" \
  python -m alembic upgrade head
DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/agentic_engine_test" \
  python -m alembic upgrade head

echo "Environment ready: PostgreSQL 16 + pgvector (agentic_engine, agentic_engine_test), RabbitMQ, and project deps installed."
