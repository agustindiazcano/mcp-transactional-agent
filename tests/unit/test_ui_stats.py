from datetime import UTC, datetime, timedelta

from src.ui.stats import compute_p95_latency, compute_throughput


def _row(created_at: datetime, updated_at: datetime) -> dict:
    return {"created_at": created_at, "updated_at": updated_at, "status": "COMPLETED"}


def test_compute_throughput_counts_rows_in_window() -> None:
    now = datetime.now(UTC)
    rows = [
        _row(now - timedelta(seconds=10), now - timedelta(seconds=5)),
        _row(now - timedelta(seconds=90), now - timedelta(seconds=80)),  # outside 60s window
        _row(now - timedelta(seconds=30), now - timedelta(seconds=20)),
    ]

    throughput = compute_throughput(rows, window_seconds=60, now=now)

    assert throughput == 2


def test_compute_throughput_empty_rows_is_zero() -> None:
    assert compute_throughput([], window_seconds=60) == 0


def test_compute_p95_latency_over_rows() -> None:
    now = datetime.now(UTC)
    # Latencies (seconds): 1, 2, 3, ..., 20 -- p95 of a 1..20 sequence is 19.05.
    rows = [
        _row(now - timedelta(seconds=i), now)
        for i in range(1, 21)
    ]

    p95 = compute_p95_latency(rows)

    assert p95 is not None
    assert 18.0 <= p95 <= 20.0


def test_compute_p95_latency_empty_rows_is_none() -> None:
    assert compute_p95_latency([]) is None
