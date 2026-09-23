import time

import httpx
import pytest

from tests.performance.chaos_idempotency import build_submission_plan, submit_all
from tests.performance.processing_throughput import Processed, percentile, summarize


def test_percentile_interpolates_between_ranks() -> None:
    values = [float(v) for v in range(1, 101)]

    assert percentile(values, 50) == pytest.approx(50.5)
    assert percentile(values, 95) == pytest.approx(95.05)
    assert percentile([7.0], 99) == 7.0


def test_percentile_of_nothing_is_an_error() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)


def _rows(count: int, spacing: float, service: float) -> list[Processed]:
    """Claims taken one after another, each `service` seconds long."""
    return [
        Processed(f"r-{i}", "COMPLETED", started=i * spacing, finished=i * spacing + service)
        for i in range(count)
    ]


def test_throughput_is_claims_over_first_start_to_last_finish() -> None:
    report = summarize(_rows(10, spacing=1.0, service=1.0), accepted_at={}, clock_offset=0.0)

    # First start 0s, last finish 10s.
    assert report.processed == 10
    assert report.wall_seconds == pytest.approx(10.0)
    assert report.throughput_per_s == pytest.approx(1.0)
    assert report.status_counts == {"COMPLETED": 10}


def test_steady_throughput_ignores_the_ramp() -> None:
    # A slow start (first 10 finish 1s apart), then 90 finish 0.1s apart.
    rows = [Processed(f"a-{i}", "COMPLETED", i * 1.0, i * 1.0 + 0.05) for i in range(10)]
    rows += [Processed(f"b-{i}", "COMPLETED", 10 + i * 0.1, 10 + i * 0.1 + 0.05)
             for i in range(90)]

    report = summarize(rows, accepted_at={}, clock_offset=0.0, trim=0.1)

    assert report.steady_throughput_per_s == pytest.approx(10.0, rel=0.05)
    assert report.throughput_per_s < 6


def test_service_time_is_created_to_updated() -> None:
    report = summarize(_rows(20, spacing=1.0, service=0.2), accepted_at={}, clock_offset=0.0)

    assert report.service_ms["p50"] == pytest.approx(200.0)
    assert report.service_ms["p95"] == pytest.approx(200.0)


def test_end_to_end_latency_uses_the_accept_time_on_the_db_clock() -> None:
    rows = [Processed("r-0", "COMPLETED", started=105.0, finished=105.5)]
    # Accepted at 1.0 on the host clock; the DB clock runs 100s ahead of it.
    report = summarize(rows, accepted_at={"r-0": 1.0}, clock_offset=100.0)

    assert report.queue_wait_ms["p50"] == pytest.approx(4000.0)
    assert report.end_to_end_ms["p50"] == pytest.approx(4500.0)


def test_latency_is_empty_without_accept_times() -> None:
    report = summarize(_rows(3, 1.0, 0.1), accepted_at={}, clock_offset=0.0)

    assert report.end_to_end_ms == {}
    assert report.queue_wait_ms == {}


def test_summarize_needs_rows() -> None:
    with pytest.raises(ValueError):
        summarize([], accepted_at={}, clock_offset=0.0)


def _accept_all(request: httpx.Request) -> httpx.Response:
    return httpx.Response(202)


@pytest.mark.asyncio
async def test_submit_all_records_when_each_claim_was_accepted() -> None:
    plan = build_submission_plan("r", total=5, dup_rate=0.0, seed=0)
    before = time.time()

    stats = await submit_all("http://gw", plan, concurrency=5, max_attempts=1,
                             transport=httpx.MockTransport(_accept_all))

    assert set(stats.accepted_at) == {c.request_id for c in plan}
    assert all(before <= t <= time.time() for t in stats.accepted_at.values())


@pytest.mark.asyncio
async def test_submit_all_paces_submissions_at_the_given_rate() -> None:
    plan = build_submission_plan("r", total=6, dup_rate=0.0, seed=0)

    stats = await submit_all("http://gw", plan, concurrency=6, max_attempts=1,
                             rate=20.0, transport=httpx.MockTransport(_accept_all))

    # 6 claims at 20/s: the last one is sent 5/20 = 0.25s after the first.
    times = sorted(stats.accepted_at.values())
    assert times[-1] - times[0] == pytest.approx(0.25, abs=0.08)
