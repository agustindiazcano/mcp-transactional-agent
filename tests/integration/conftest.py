"""Create the isolated test database if needed and migrate it to head once
per session, so every integration test sees the schema Alembic produces."""
import asyncio

import pytest

from src.core.config import settings
from tests.support.database import ensure_database_exists, migrate_to_head


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database() -> None:
    """Sync on purpose: runs before pytest-asyncio's loop exists."""
    asyncio.run(ensure_database_exists(settings.DATABASE_URL))
    migrate_to_head()
