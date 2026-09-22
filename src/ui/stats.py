"""Pure, dependency-free stats computed from transaction rows already
fetched from the gateway (src/ui/api_client.py). No I/O here -- fully
unit-testable in isolation, mirroring the confidence layer's "pure function
of its inputs" rule (CLAUDE.md Section 4)."""
from datetime import UTC, datetime
from typing import Any


def compute_throughput(
    rows: list[dict[str, Any]],
    *,
    window_seconds: int = 60,
    now: datetime | None = None,
) -> int:
    """Count rows whose created_at falls within the trailing window."""
    if not rows:
        return 0
    reference = now or datetime.now(UTC)
    cutoff = reference.timestamp() - window_seconds
    return sum(1 for row in rows if row["created_at"].timestamp() >= cutoff)


def compute_p95_latency(rows: list[dict[str, Any]]) -> float | None:
    """95th-percentile latency (seconds) between created_at and updated_at.

    Returns None when there are no rows to compute over -- callers should
    render that as "no data yet", not a hardcoded 0.
    """
    if not rows:
        return None
    latencies = sorted(
        (row["updated_at"] - row["created_at"]).total_seconds() for row in rows
    )
    index = min(round(0.95 * (len(latencies) - 1)), len(latencies) - 1)
    return float(latencies[index])
