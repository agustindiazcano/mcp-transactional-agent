---
name: db-migration
description: >-
  Use this skill when the user asks to create, review, apply, or roll back a
  database migration using Alembic. Enforces safe migration practices to
  prevent data loss in PostgreSQL with the pgvector extension.
---

# Database Migration Runbook

Alembic migrations are irreversible in production if they drop data. Follow
this procedure for every migration, no matter how small.

## Step 1 - Confirm the Model Change

Before generating a migration, verify that `app/models.py` already reflects
the intended schema change. The migration should be generated from the model,
not written by hand.

## Step 2 - Generate the Migration

```bash
alembic revision --autogenerate -m "<short_description_of_change>"
```

Use a descriptive message: `add_request_id_index`, `add_embedding_column`, etc.

## Step 3 - Review the Generated File

Open the file in `alembic/versions/`. Check:

- Are there any DROP TABLE or DROP COLUMN operations that were not intended?
- If adding an index, is it CONCURRENTLY to avoid locking? (Use `postgresql_concurrently=True` in SQLAlchemy.)
- If adding a pgvector column, is the extension already installed? (`CREATE EXTENSION IF NOT EXISTS vector`)
- Is the `downgrade()` function correct and safe?

If the migration contains unintended destructive operations, delete the file
and fix the model before regenerating.

## Step 4 - Test the Migration on a Local Copy

```bash
# Apply
alembic upgrade head

# Verify current state
alembic current

# Optionally test rollback
alembic downgrade -1
alembic upgrade head
```

Run the test suite after applying to confirm nothing is broken:

```bash
pytest tests/ -v --tb=short
```

## Step 5 - Apply to Staging

Apply the migration on the staging environment before production:

```bash
DATABASE_URL=<staging_url> alembic upgrade head
```

## Step 6 - Rules for Safe Migrations

- Never drop a column without first deprecating it in code (two-phase migration).
- Never rename a column in a single migration; add the new column, backfill, then drop the old one.
- Never run `alembic downgrade base` in production.
- For pgvector index creation on large tables, use `CREATE INDEX CONCURRENTLY`.
- Always back up the database before applying migrations to production.

## Step 7 - Validate in Production

After applying in production:

```bash
alembic current  # Should show the new head revision
```

Confirm the application starts without errors and the health check endpoint returns 200.
