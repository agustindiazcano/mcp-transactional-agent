---
name: db-migration
description: >-
  Use this skill when the user asks to create, review, apply, or roll back a
  database migration using Alembic. Enforces safe migration practices for
  PostgreSQL, including the pgvector extension (Phase 1.D).
---

# Database Migration Runbook

Alembic migrations are hard to reverse in production if they drop data.
Follow this procedure for every migration, no matter how small. Any migration
that drops a column or table is flagged in CLAUDE.md Section 8 — pause and
confirm intent with the user before writing one.

## Step 1 - Confirm the Model Change

Before generating a migration, verify `src/core/models.py` already reflects
the intended schema change. Generate the migration from the model; don't
hand-write it.

## Step 2 - Generate the Migration

```bash
alembic revision --autogenerate -m "<short_description_of_change>"
```

Use a descriptive message: `add_request_id_index`, `add_embedding_column`, etc.

## Step 3 - Review the Generated File

Open the file in `alembic/versions/`. Check:

- Any unintended `DROP TABLE`/`DROP COLUMN`?
- New index: `CONCURRENTLY` to avoid locking? (`postgresql_concurrently=True` in SQLAlchemy.)
- Adding a `pgvector` column: is the extension enabled yet? As of this writing it is **not** — enabling it is Phase 1.D's first scope item (`CREATE EXTENSION IF NOT EXISTS vector`), still pending. If this migration is the one enabling it, that's expected; if it assumes the extension already exists, it will fail.
- Is `downgrade()` correct and safe?

If the migration contains unintended destructive operations, delete the file
and fix the model before regenerating.

## Step 4 - Test the Migration Locally

```bash
alembic upgrade head
alembic current
# optionally test rollback
alembic downgrade -1
alembic upgrade head
```

Then run the suite:

```bash
pytest tests/ -v --tb=short
```

## Step 5 - Rules for Safe Migrations

- Never drop a column without deprecating it in code first (two-phase migration).
- Never rename a column in one migration; add the new column, backfill, then drop the old one in a later migration.
- Never run `alembic downgrade base` against a database with real data.
- For a `pgvector` index on a large table, use `CREATE INDEX CONCURRENTLY`.

## Step 6 - Validate After Applying

```bash
alembic current  # should show the new head revision
```

If running under Docker Compose (Phase 1.C), migrations run automatically via
the one-shot `migrate` service (`alembic upgrade head`) before the app
services start — see `docker-compose.yml`.
