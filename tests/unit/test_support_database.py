"""Unit tests for tests.support.database: the guard that keeps the test
suite off the dev database. Pure URL logic -- no Postgres needed."""
import pytest

from tests.support.database import UnsafeTestDatabaseError, resolve_test_database_url

DEV_URL = "postgresql+asyncpg://postgres:password@localhost:5432/agentic_engine"


def test_derives_test_database_on_same_server() -> None:
    url = resolve_test_database_url(DEV_URL)

    assert url == "postgresql+asyncpg://postgres:password@localhost:5432/agentic_engine_test"


def test_explicit_test_database_url_is_used_as_is() -> None:
    explicit = "postgresql+asyncpg://ci:secret@db:5433/ci_run_test"

    assert resolve_test_database_url(DEV_URL, explicit) == explicit


def test_explicit_url_without_test_suffix_is_refused() -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        resolve_test_database_url(DEV_URL, "postgresql+asyncpg://postgres:password@localhost/prod")


def test_explicit_url_pointing_at_dev_database_is_refused() -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        resolve_test_database_url(DEV_URL, DEV_URL)


def test_dev_database_already_named_test_is_refused() -> None:
    """If DATABASE_URL itself ends in _test and no TEST_DATABASE_URL is set,
    the derived name must still differ from it."""
    dev_named_test = "postgresql+asyncpg://postgres:password@localhost/shared_test"

    url = resolve_test_database_url(dev_named_test)

    assert url.endswith("/shared_test_test")
