"""Keeps the test suite off the dev database.

Integration fixtures TRUNCATE whole tables, so they must never run against
DATABASE_URL (the dev DB, which holds real transactions and the RAG
knowledge base). Tests run against a separate database instead: the one in
TEST_DATABASE_URL, or `<dev db name>_test` on the same server. It is created
on demand and brought to `alembic upgrade head`, so the schema under test is
the one the migrations produce -- never Base.metadata.create_all().
"""
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEST_SUFFIX = "_test"


class UnsafeTestDatabaseError(RuntimeError):
    """The resolved test database could be the dev (or any non-test) DB."""


def resolve_test_database_url(database_url: str, test_database_url: str = "") -> str:
    """Return the URL the test suite may use, refusing anything unsafe.

    Fails closed: the database name must end in `_test` and differ from the
    dev database's, whether it was given explicitly or derived.
    """
    dev = make_url(database_url)
    if test_database_url:
        test = make_url(test_database_url)
    else:
        test = dev.set(database=f"{dev.database}{_TEST_SUFFIX}")

    name = test.database or ""
    if not name.endswith(_TEST_SUFFIX) or (
        name == dev.database and test.host == dev.host and test.port == dev.port
    ):
        raise UnsafeTestDatabaseError(
            f"Refusing to run tests against database {name!r}: its name must end in "
            f"{_TEST_SUFFIX!r} and differ from DATABASE_URL's ({dev.database!r})."
        )
    return test.render_as_string(hide_password=False)


async def ensure_database_exists(url: str) -> None:
    """Create the test database if it is missing (via the `postgres` DB)."""
    target = make_url(url)
    maintenance = target.set(database="postgres")
    engine = create_async_engine(maintenance, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            )
            if not exists:
                quoted = target.database.replace('"', '""') if target.database else ""
                await conn.execute(text(f'CREATE DATABASE "{quoted}"'))
    finally:
        await engine.dispose()


def migrate_to_head() -> None:
    """Run `alembic upgrade head` against os.environ["DATABASE_URL"].

    alembic/env.py reads the URL from that variable, so the caller must point
    it at the test database first. Built without alembic.ini on purpose: its
    fileConfig() would reconfigure logging mid-session.
    """
    config = Config()
    config.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    command.upgrade(config, "head")
