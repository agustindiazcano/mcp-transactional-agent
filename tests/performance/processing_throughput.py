"""Processing throughput: how fast the worker pool resolves claims, end to end.

The Locust numbers measure ingestion only (the gateway's 202 once a claim is
queued). This measures processing: the Prompt Guard, retrieval, the Double
Judge and the refund through the MCP boundary, with every LLM role on the mock
so the result is the pipeline's own cost, not a provider's latency.

Run once per worker count against the stack with the chaos override (mock
providers, MCP rate limit lifted) and the scaling override (lets compose run
more than one worker container):

    docker compose -f docker-compose.yml -f docker-compose.chaos.yml \\
        -f docker-compose.scale.yml up -d --scale worker=4
    python -m tests.performance.processing_throughput --claims 1000

Three modes:
- burst (default, ``--rate 0``): the whole plan is queued at once, so the
  drain rate is the pool's maximum throughput. Queue wait dominates latency.
- ``--prefill``: the workers are paused (``docker pause``) while the plan is
  queued and unpaused once it all is, so the drain rate is the pool's capacity
  even when ingestion is slower than processing. Pause, not stop: a stopped
  worker cold-boots on start (imports alone take seconds of CPU each), which
  would land inside the measured window and weigh more with every worker
  added. A paused worker keeps its broker connection; queueing must finish
  well within the AMQP heartbeat timeout (60s).
- paced (``--rate R``): claims arrive at R/s. Below capacity, the end-to-end
  latency is what a single claim sees without a backlog.

Timings:
- ``service_ms``: ``created_at`` -> ``updated_at``, both on the DB clock. The
  worker creates the row when it takes the message, so this excludes queueing.
- ``queue_wait_ms`` / ``end_to_end_ms``: from the gateway's 202 (host clock,
  shifted onto the DB clock by a measured offset) to the row's creation / final
  write.
"""

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.core.config import settings
from tests.performance.chaos_idempotency import (
    build_submission_plan,
    drive_faults_and_drain,
    seed_plan_orders,
    submit_all,
)

# ── Analysis ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Processed:
    """One claim of the run, with its DB timestamps as epoch seconds."""

    request_id: str
    status: str
    started: float
    finished: float


@dataclass
class ThroughputReport:
    """Throughput and latency of one run."""

    processed: int
    status_counts: dict[str, int]
    wall_seconds: float
    throughput_per_s: float
    steady_throughput_per_s: float
    service_ms: dict[str, float]
    queue_wait_ms: dict[str, float]
    end_to_end_ms: dict[str, float]


def percentile(values: Sequence[float], q: float) -> float:
    """The q-th percentile (0-100), linearly interpolated between ranks."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _distribution_ms(seconds: Sequence[float]) -> dict[str, float]:
    if not seconds:
        return {}
    return {f"p{q}": round(percentile(seconds, q) * 1000, 1) for q in (50, 95, 99)} | {
        "max": round(max(seconds) * 1000, 1)
    }


def _steady_throughput(finish_times: list[float], trim: float) -> float:
    """Completions per second between the ``trim`` and ``1 - trim`` quantiles.

    Leaves out the ramp-up (workers taking their first message) and the tail
    (the last workers finishing alone), which drag the overall average down.
    """
    ordered = sorted(finish_times)
    low = int(len(ordered) * trim)
    high = len(ordered) - 1 - low
    span = ordered[high] - ordered[low]
    if high <= low or span <= 0:
        return 0.0
    return (high - low) / span


def summarize(
    rows: list[Processed],
    accepted_at: dict[str, float],
    clock_offset: float,
    trim: float = 0.1,
) -> ThroughputReport:
    """Compute the run's throughput and latency distributions.

    ``clock_offset`` is DB clock minus host clock, added to the host-side
    accept times so every latency is measured on the DB clock.
    """
    if not rows:
        raise ValueError("no processed claims to summarize")

    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1

    wall = max(r.finished for r in rows) - min(r.started for r in rows)
    accepted = [(r, accepted_at[r.request_id] + clock_offset)
                for r in rows if r.request_id in accepted_at]

    return ThroughputReport(
        processed=len(rows),
        status_counts=status_counts,
        wall_seconds=round(wall, 3),
        throughput_per_s=round(len(rows) / wall, 2) if wall > 0 else 0.0,
        steady_throughput_per_s=round(_steady_throughput([r.finished for r in rows], trim), 2),
        service_ms=_distribution_ms([r.finished - r.started for r in rows]),
        queue_wait_ms=_distribution_ms([r.started - at for r, at in accepted]),
        end_to_end_ms=_distribution_ms([r.finished - at for r, at in accepted]),
    )


# ── Measurement ─────────────────────────────────────────────────────────────


async def _docker(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "docker", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed: {stderr.decode().strip()}")
    return stdout.decode()


async def worker_containers() -> list[str]:
    """IDs of the worker containers compose is running right now."""
    return (await _docker(
        "ps", "-q", "--filter", "label=com.docker.compose.service=worker"
    )).split()


async def db_clock_offset(engine: AsyncEngine) -> float:
    """DB clock minus host clock, in seconds (error bounded by half the round trip)."""
    async with engine.connect() as conn:
        before = time.time()
        db_now = (await conn.execute(
            text("SELECT extract(epoch FROM clock_timestamp())")
        )).scalar_one()
        after = time.time()
    return float(db_now) - (before + after) / 2


async def fetch_processed(engine: AsyncEngine, prefix: str) -> list[Processed]:
    """This run's rows that left PROCESSING."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT request_id, status, extract(epoch FROM created_at), "
                 "extract(epoch FROM updated_at) FROM transactions "
                 "WHERE request_id LIKE :p AND status <> 'PROCESSING'"),
            {"p": f"{prefix}%"},
        )
        return [Processed(r[0], r[1], float(r[2]), float(r[3])) for r in result]


async def run(args: argparse.Namespace) -> int:
    """Execute one throughput run and print its report; return the exit code."""
    workers = await worker_containers()
    if not workers:
        raise RuntimeError("no worker container is running")
    run_id = args.run_id or f"tput-w{len(workers)}-{int(time.time())}"
    plan = build_submission_plan(run_id, args.claims, dup_rate=0.0, seed=args.seed)
    engine = create_async_engine(args.database_url)

    try:
        await seed_plan_orders(engine, plan)
        offset = await db_clock_offset(engine)
        submit = submit_all(args.gateway_url, plan, args.concurrency, args.max_attempts,
                            rate=args.rate)
        if args.prefill:
            await _docker("pause", *workers)
            try:
                submit_task = asyncio.ensure_future(submit)
                await submit_task
            finally:
                # Never leave the pool frozen, even if submission failed.
                await _docker("unpause", *workers)
        else:
            submit_task = asyncio.ensure_future(submit)
        _, drain_seconds = await drive_faults_and_drain(
            engine, run_id, len(plan), faults=[], idle_timeout=args.idle_timeout
        )
        stats = await submit_task
        rows = await fetch_processed(engine, run_id)
    finally:
        await engine.dispose()

    report = summarize(rows, stats.accepted_at, offset)
    complete = report.processed == len(plan)
    output = {
        "run_id": run_id,
        "workers": len(workers),
        "claims": len(plan),
        "mode": ("prefill" if args.prefill
                 else f"paced {args.rate}/s" if args.rate > 0 else "burst"),
        "ingestion_seconds": round(stats.seconds, 1),
        "drain_seconds": round(drain_seconds, 1),
        "clock_offset_ms": round(offset * 1000, 1),
        "complete": complete,
        **asdict(report),
    }
    sys.stdout.write(json.dumps(output, indent=2) + "\n")
    return 0 if complete else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claims", type=int, default=1000)
    parser.add_argument("--rate", type=float, default=0.0,
                        help="claims per second; 0 queues the whole plan at once")
    parser.add_argument("--prefill", action="store_true",
                        help="queue the whole plan with the workers paused, then unpause them")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--max-attempts", type=int, default=30)
    parser.add_argument("--idle-timeout", type=float, default=90.0)
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8000")
    parser.add_argument("--database-url", default=settings.DATABASE_URL)
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(run(_parse_args())))
