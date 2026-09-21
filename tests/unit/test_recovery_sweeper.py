"""Unit tests for recovery_sweeper.run_sweep().

TDD Red-Green cycle:
  Red  — tests fail because recovery_sweeper.py does not exist yet.
  Green — pass after the sweeper is implemented.

Tests:
  1. No zombie rows -> no publish, no delete.
  2. One zombie row -> DELETE called, payload re-published to RabbitMQ.
"""
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zombie_txn(request_id: str = "req-zombie-001", payload: dict | None = None) -> MagicMock:
    txn = MagicMock()
    txn.request_id = request_id
    txn.payload = payload or {"request_id": request_id, "claim_text": "refund 50"}
    txn.updated_at = datetime(2000, 1, 1, tzinfo=UTC)  # ancient
    return txn


def _make_db_session(zombie_rows: list) -> AsyncMock:
    session = AsyncMock()
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=zombie_rows)
    execute_result = MagicMock()
    execute_result.scalars = MagicMock(return_value=scalars_result)
    session.execute = AsyncMock(return_value=execute_result)
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_zombie_rows_does_nothing() -> None:
    """When no stale rows exist, the sweeper does nothing."""
    db_session = _make_db_session(zombie_rows=[])
    mock_channel = AsyncMock()

    with patch("src.worker.recovery_sweeper.settings") as mock_settings:
        mock_settings.SWEEPER_STALE_THRESHOLD_SECONDS = 300

        from src.worker.recovery_sweeper import run_sweep

        await run_sweep(db_session, mock_channel)

    # No deletes, no publishes
    db_session.delete.assert_not_called()
    mock_channel.default_exchange.publish.assert_not_awaited()
    db_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_zombie_row_deleted_and_requeued() -> None:
    """A zombie row is deleted from Postgres and its payload re-published to RabbitMQ."""
    zombie = _zombie_txn()
    db_session = _make_db_session(zombie_rows=[zombie])

    mock_exchange = AsyncMock()
    mock_channel = AsyncMock()
    mock_channel.default_exchange = mock_exchange

    with (
        patch("src.worker.recovery_sweeper.settings") as mock_settings,
        patch("src.worker.recovery_sweeper.aio_pika") as mock_pika,
    ):
        mock_settings.SWEEPER_STALE_THRESHOLD_SECONDS = 300
        # aio_pika.Message should return a fake message object
        fake_msg = MagicMock()
        mock_pika.Message = MagicMock(return_value=fake_msg)

        from src.worker.recovery_sweeper import run_sweep

        await run_sweep(db_session, mock_channel)

    # Row must be deleted
    db_session.delete.assert_called_once_with(zombie)
    # Payload must be re-published
    mock_pika.Message.assert_called_once_with(
        json.dumps(zombie.payload).encode(),
        delivery_mode=mock_pika.DeliveryMode.PERSISTENT,
    )
    mock_exchange.publish.assert_awaited_once_with(
        fake_msg, routing_key="agent_tasks_queue"
    )
    db_session.commit.assert_awaited_once()
