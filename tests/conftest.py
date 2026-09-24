"""Point the whole test run at the isolated test database, before any test
touches `settings.DATABASE_URL` -- see tests/support/database.py.

Done at import time (not in a fixture) so it also covers module-level code
and alembic/env.py, which reads os.environ["DATABASE_URL"]. Refuses to start
if the resolved database could be the dev DB.
"""
import os

import pytest

from src.core.config import settings
from tests.support.database import UnsafeTestDatabaseError, resolve_test_database_url

try:
    _TEST_DATABASE_URL = resolve_test_database_url(
        settings.DATABASE_URL, settings.TEST_DATABASE_URL
    )
except UnsafeTestDatabaseError as exc:
    pytest.exit(str(exc), returncode=4)

settings.DATABASE_URL = _TEST_DATABASE_URL
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL

# Tracing is off for the whole run, even with Langfuse keys in .env; a test
# that asserts on spans opts in with the in-memory `trace_exporter` fixture.
from src.core import tracing
from tests.support.tracing import trace_exporter  # noqa: F401

settings.LANGFUSE_TRACING_ENABLED = False
tracing.configure_tracing(None)
