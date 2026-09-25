"""Chaos/idempotency test: correctness of the pipeline under load and faults.

Sends N claims to the gateway, about DUP_RATE of them deliberate duplicates
(an earlier claim's request_id, sent again). While the backlog drains, it
kills the worker twice and restarts RabbitMQ once. At the end it checks in
PostgreSQL that:

- no request_id was refunded twice (``refunds`` has one row per request_id);
- no accepted claim was lost (every request_id reached a final state);
- nothing is left stuck in PROCESSING;
- every COMPLETED transaction has its refund, and every refund its COMPLETED
  transaction.

Runs against the docker compose stack with every LLM role on the mock, so it
makes no paid calls (see docker-compose.chaos.yml):

    docker compose -f docker-compose.yml -f docker-compose.chaos.yml up -d
    python -m tests.performance.chaos_idempotency --claims 2000

Rows are tagged with a per-run request_id prefix and left in the database, so
a run can be inspected afterwards; every query is scoped to that prefix.
"""

import argparse
import asyncio
import json
import random
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.core.config import settings
from src.core.database import get_session_maker
from src.core.repositories.order_repository import insert_orders_if_absent

logger = structlog.get_logger("chaos_idempotency")

FINAL_STATUSES = (
    "COMPLETED",
    "PENDING_HUMAN_REVIEW",
    "EXECUTION_FAILED",
    "BLOCKED_MALICIOUS_PROMPT",
)
WORKER_CONTAINER = "agentic_worker"
BROKER_CONTAINER = "agentic_mq"


# ── Plan ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Claim:
    """One claim submission. A duplicate reuses an earlier claim's body."""

    request_id: str
    body: dict[str, Any]
    is_duplicate: bool


def build_submission_plan(run_id: str, total: int, dup_rate: float, seed: int) -> list[Claim]:
    """Return ``total`` submissions, ``round(total * dup_rate)`` of them duplicates.

    Each duplicate is sent after its original, with the identical body, so it is
    what a client retry or a redelivered message looks like to the pipeline.
    """
    if total < 1 or not 0 <= dup_rate < 1:
        raise ValueError("total must be >= 1 and dup_rate in [0, 1)")
    rng = random.Random(seed)
    duplicates = round(total * dup_rate)
    unique = total - duplicates

    originals = [
        Claim(
            request_id=f"{run_id}-{i:05d}",
            body={
                "request_id": f"{run_id}-{i:05d}",
                "user_id": f"chaos-user-{i % 50}",
                "claim_text": "My order arrived damaged, please refund it.",
                "order_id": f"{run_id}-ord-{i:05d}",
                "amount": round(10 + (i % 90) + 0.5, 2),
                "currency": "USD",
            },
            is_duplicate=False,
        )
        for i in range(unique)
    ]
    plan = list(originals)
    for _ in range(duplicates):
        # Insert after the original, so the duplicate never arrives first.
        original_index = rng.randrange(unique)
        original = originals[original_index]
        position = rng.randint(plan.index(original) + 1, len(plan))
        plan.insert(position, Claim(original.request_id, original.body, is_duplicate=True))
    return plan


def orders_for_plan(plan: list[Claim]) -> list[dict[str, Any]]:
    """One order per unique claim, matching its user, amount and currency.

    The worker checks each refund against its order before the judges
    (Part B), so a claim whose order doesn't exist would go to human review.
    """
    orders: dict[str, dict[str, Any]] = {}
    for claim in plan:
        body = claim.body
        orders.setdefault(body["order_id"], {
            "order_id": body["order_id"],
            "user_id": body["user_id"],
            "amount": body["amount"],
            "currency": body["currency"],
        })
    return list(orders.values())


async def seed_plan_orders(engine: AsyncEngine, plan: list[Claim]) -> int:
    """Insert the plan's orders that are missing; returns how many were added."""
    async with get_session_maker(engine)() as session:
        return await insert_orders_if_absent(session, orders_for_plan(plan))


# ── Verdict ─────────────────────────────────────────────────────────────────


@dataclass
class Outcome:
    """What the database says after the run drained."""

    accepted_unique: int
    status_counts: dict[str, int]
    missing: int
    stuck_processing: int
    refund_rows: int
    refunded_request_ids: int
    completed_without_refund: int
    refund_without_completed: int
    already_executed_replays: int

    @property
    def double_refunds(self) -> int:
        """Refund rows beyond the first for any request_id."""
        return self.refund_rows - self.refunded_request_ids

    @property
    def lost(self) -> int:
        """Accepted claims that never reached a final state."""
        return self.missing + self.stuck_processing

    def failures(self) -> list[str]:
        """Every invariant the run broke; empty means the run passed."""
        problems = []
        if self.double_refunds:
            problems.append(f"{self.double_refunds} double refund(s)")
        if self.missing:
            problems.append(f"{self.missing} accepted claim(s) with no transaction row")
        if self.stuck_processing:
            problems.append(f"{self.stuck_processing} transaction(s) stuck in PROCESSING")
        if self.completed_without_refund:
            problems.append(f"{self.completed_without_refund} COMPLETED without a refund")
        if self.refund_without_completed:
            problems.append(f"{self.refund_without_completed} refund(s) without COMPLETED")
        return problems


# ── Submission ──────────────────────────────────────────────────────────────


@dataclass
class SubmitStats:
    """Gateway-side counters for the submission phase."""

    accepted: int = 0
    # Host wall-clock time of each request_id's first 202, for latency.
    accepted_at: dict[str, float] = field(default_factory=dict)
    retried_attempts: int = 0
    gave_up: list[str] = field(default_factory=list)
    seconds: float = 0.0


async def _submit_one(
    client: httpx.AsyncClient, claim: Claim, stats: SubmitStats, max_attempts: int
) -> None:
    """POST one claim, retrying (same request_id) until the gateway returns 202.

    Retrying with the same request_id is safe by design: a claim that was in
    fact published before the error is deduplicated by the worker.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.post("/api/v1/claims", json=claim.body)
            if response.status_code == 202:
                stats.accepted += 1
                stats.accepted_at.setdefault(claim.request_id, time.time())
                return
            logger.warning("submit_rejected", request_id=claim.request_id,
                           status=response.status_code)
        except httpx.HTTPError as exc:
            logger.warning("submit_error", request_id=claim.request_id, error=repr(exc))
        stats.retried_attempts += 1
        await asyncio.sleep(min(0.5 * 2 ** (attempt - 1), 5.0))
    stats.gave_up.append(claim.request_id)


async def submit_all(
    gateway_url: str,
    plan: list[Claim],
    concurrency: int,
    max_attempts: int,
    rate: float = 0.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SubmitStats:
    """Submit the whole plan with bounded concurrency, in plan order.

    With ``rate`` > 0, claim i is not sent before ``i / rate`` seconds into the
    run (an open-loop arrival rate); 0 sends as fast as concurrency allows.
    """
    stats = SubmitStats()
    semaphore = asyncio.Semaphore(concurrency)
    started = time.monotonic()

    async with httpx.AsyncClient(
        base_url=gateway_url, timeout=10.0, transport=transport
    ) as client:

        async def bounded(index: int, claim: Claim) -> None:
            if rate > 0:
                await asyncio.sleep(max(0.0, started + index / rate - time.monotonic()))
            async with semaphore:
                await _submit_one(client, claim, stats, max_attempts)

        await asyncio.gather(*(bounded(i, claim) for i, claim in enumerate(plan)))

    stats.seconds = time.monotonic() - started
    return stats


# ── Faults ──────────────────────────────────────────────────────────────────


async def _docker(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "docker", *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed: {stderr.decode().strip()}")


async def kill_worker(down_seconds: float) -> None:
    """SIGKILL the worker mid-message, then start it again, as an orchestrator would."""
    await _docker("kill", WORKER_CONTAINER)
    await asyncio.sleep(down_seconds)
    await _docker("start", WORKER_CONTAINER)


async def restart_broker() -> None:
    """Restart RabbitMQ with messages still queued."""
    await _docker("restart", BROKER_CONTAINER)


@dataclass(frozen=True)
class Fault:
    """A fault fired once ``at_fraction`` of the unique claims are final."""

    name: str
    at_fraction: float
    action: Callable[[], Awaitable[None]]


# ── Database ────────────────────────────────────────────────────────────────


async def count_final(engine: AsyncEngine, prefix: str) -> int:
    """Transactions of this run that reached a final state."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT count(*) FROM transactions "
                 "WHERE request_id LIKE :p AND status = ANY(:final)"),
            {"p": f"{prefix}%", "final": list(FINAL_STATUSES)},
        )
        return int(result.scalar_one())


async def collect_outcome(engine: AsyncEngine, prefix: str, accepted_ids: set[str]) -> Outcome:
    """Read the invariants for this run's rows."""
    like = {"p": f"{prefix}%"}
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT request_id, status, judge_trail -> 'execution' ->> 'status' "
                 "FROM transactions WHERE request_id LIKE :p"),
            like,
        )
        transactions = {r[0]: (r[1], r[2]) for r in rows}

        refunds = (await conn.execute(
            text("SELECT count(*), count(DISTINCT request_id) FROM refunds "
                 "WHERE request_id LIKE :p"),
            like,
        )).one()
        completed_without_refund = (await conn.execute(
            text("SELECT count(*) FROM transactions t WHERE t.request_id LIKE :p "
                 "AND t.status = 'COMPLETED' AND NOT EXISTS "
                 "(SELECT 1 FROM refunds r WHERE r.request_id = t.request_id)"),
            like,
        )).scalar_one()
        refund_without_completed = (await conn.execute(
            text("SELECT count(*) FROM refunds r WHERE r.request_id LIKE :p "
                 "AND NOT EXISTS (SELECT 1 FROM transactions t "
                 "WHERE t.request_id = r.request_id AND t.status = 'COMPLETED')"),
            like,
        )).scalar_one()

    status_counts: dict[str, int] = {}
    for status, _ in transactions.values():
        status_counts[status] = status_counts.get(status, 0) + 1

    return Outcome(
        accepted_unique=len(accepted_ids),
        status_counts=status_counts,
        missing=len(accepted_ids - transactions.keys()),
        stuck_processing=status_counts.get("PROCESSING", 0),
        refund_rows=int(refunds[0]),
        refunded_request_ids=int(refunds[1]),
        completed_without_refund=int(completed_without_refund),
        refund_without_completed=int(refund_without_completed),
        already_executed_replays=sum(
            1 for _, execution in transactions.values() if execution == "already_executed"
        ),
    )


# ── Run ─────────────────────────────────────────────────────────────────────


async def drive_faults_and_drain(
    engine: AsyncEngine,
    prefix: str,
    unique_total: int,
    faults: list[Fault],
    idle_timeout: float,
) -> tuple[list[dict[str, Any]], float]:
    """Fire each fault at its progress mark, then wait for the backlog to drain.

    Draining ends when every unique claim is final, or when no claim has become
    final for ``idle_timeout`` seconds (which must cover the sweeper window).
    """
    fired: list[dict[str, Any]] = []
    pending = sorted(faults, key=lambda f: f.at_fraction)
    started = time.monotonic()
    last_progress, last_count = time.monotonic(), -1

    while True:
        done = await count_final(engine, prefix)
        if done != last_count:
            last_progress, last_count = time.monotonic(), done
        while pending and done >= pending[0].at_fraction * unique_total:
            fault = pending.pop(0)
            logger.warning("fault_injected", fault=fault.name, final_so_far=done)
            fired.append({"fault": fault.name, "final_so_far": done,
                          "t_seconds": round(time.monotonic() - started, 1)})
            await fault.action()
        if done >= unique_total and not pending:
            break
        if time.monotonic() - last_progress > idle_timeout:
            logger.error("drain_stalled", final=done, expected=unique_total)
            break
        await asyncio.sleep(1.0)

    return fired, time.monotonic() - started


async def run(args: argparse.Namespace) -> int:
    """Execute one chaos run and print its report; return the exit code."""
    run_id = args.run_id or f"chaos-{int(time.time())}"
    plan = build_submission_plan(run_id, args.claims, args.dup_rate, args.seed)
    unique_ids = {c.request_id for c in plan}
    faults = [
        Fault("kill_worker_1", 0.20, lambda: kill_worker(args.worker_down_seconds)),
        Fault("restart_rabbitmq", 0.45, restart_broker),
        Fault("kill_worker_2", 0.70, lambda: kill_worker(args.worker_down_seconds)),
    ]
    engine = create_async_engine(args.database_url)
    logger.info("run_started", run_id=run_id, submissions=len(plan), unique=len(unique_ids))

    try:
        await seed_plan_orders(engine, plan)
        started = time.monotonic()
        submit_task = asyncio.create_task(
            submit_all(args.gateway_url, plan, args.concurrency, args.max_attempts)
        )
        fired, _ = await drive_faults_and_drain(
            engine, run_id, len(unique_ids), faults, args.idle_timeout
        )
        stats = await submit_task
        total_seconds = time.monotonic() - started
        accepted_ids = unique_ids - set(stats.gave_up)
        outcome = await collect_outcome(engine, run_id, accepted_ids)
    finally:
        await engine.dispose()

    failures = outcome.failures()
    report = {
        "run_id": run_id,
        "submissions": len(plan),
        "unique_claims": len(unique_ids),
        "duplicates": len(plan) - len(unique_ids),
        "gateway": asdict(stats),
        "faults": fired,
        "total_seconds": round(total_seconds, 1),
        "outcome": {**asdict(outcome), "double_refunds": outcome.double_refunds,
                    "lost": outcome.lost},
        "passed": not failures,
        "failures": failures,
    }
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0 if not failures else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claims", type=int, default=2000)
    parser.add_argument("--dup-rate", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--max-attempts", type=int, default=30)
    parser.add_argument("--worker-down-seconds", type=float, default=3.0)
    parser.add_argument("--idle-timeout", type=float, default=180.0,
                        help="stop draining after this long without progress; "
                             "must exceed the sweeper's stale threshold + interval")
    parser.add_argument("--gateway-url", default="http://localhost:8000")
    parser.add_argument("--database-url", default=settings.DATABASE_URL)
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(run(_parse_args())))
