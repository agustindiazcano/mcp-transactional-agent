---
name: debug-worker
description: >-
  Use this skill when the user reports that messages are being lost,
  duplicated, or stuck in the RabbitMQ queue, or that the worker is failing
  to ACK/NACK correctly. Guides a systematic root-cause investigation without
  breaking the ACK/NACK contract or the idempotency guarantee.
---

# Worker Debugging Runbook

Use this to diagnose and fix issues in `src/worker/worker.py` (and, for
stale-transaction issues, `src/worker/recovery_sweeper.py`) without breaking
the ACK/NACK contract or the idempotency guarantee. Any change to the
ACK/NACK logic itself is flagged in CLAUDE.md Section 8 — confirm intent
before touching it.

## Step 1 - Confirm the Symptom

- Messages consumed but never ACK'd (queue grows, redelivery counter increases).
- Messages ACK'd but no database record was created (silent failure).
- Messages processed more than once (idempotency failure).
- Worker crashes with an unhandled exception.
- LLM calls time out and messages are NACK'd but not requeued.
- A `PROCESSING` row never resolves — check whether the Recovery Sweeper (`recovery_sweeper.py`, `SWEEPER_INTERVAL_SECONDS`/`SWEEPER_STALE_THRESHOLD_SECONDS`) is running at all; it's a separate process, not started automatically by `worker.py`.

## Step 2 - Check the Transactions Table

```sql
SELECT request_id, status, created_at, updated_at
FROM transactions
WHERE request_id = '<the_request_id>';
```

If the record exists and `status` is terminal (`COMPLETED`, `FAILED`,
`PENDING_HUMAN_REVIEW`), the worker should have short-circuited before
calling the LLM. If it didn't, the idempotency check
(`SELECT ... FOR UPDATE` + `UniqueConstraint` on `request_id`) is broken.

## Step 3 - Read the Structured Logs

Logs are structured JSON via `structlog`. Filter by `request_id`:

```bash
# Docker Compose (Phase 1.C)
docker compose logs worker | grep '"request_id": "<the_request_id>"'
docker compose logs sweeper | grep '"request_id": "<the_request_id>"'
```

## Step 4 - Inspect the RabbitMQ Management UI

`http://localhost:15672` (guest/guest by default). Check queue depth, the
main queue vs. the dead-letter queue, redelivery count (`x-death` header),
and connected consumers.

## Step 5 - Reproduce Locally

The worker uses `aio_pika` (async), not the synchronous `pika` library — a
reproduction script must use its async API:

```python
import asyncio, json, uuid
import aio_pika

async def main() -> None:
    conn = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
    async with conn:
        channel = await conn.channel()
        await channel.default_exchange.publish(
            aio_pika.Message(body=json.dumps({
                "request_id": str(uuid.uuid4()),
                "type": "refund",
                "amount": 10.00,
                "user_id": "test-user-1",
            }).encode()),
            routing_key="transactions",
        )

asyncio.run(main())
```

Then watch the worker logs in real time.

## Step 6 - Fix and Verify ACK/NACK Integrity

- Never move the ACK before the database commit.
- Never swallow an exception that should trigger a NACK.
- After any fix: `pytest tests/integration/test_worker.py tests/unit/test_worker_concurrency.py -v`.

## Step 7 - Validate the Fix

1. Clear the queue or use a fresh test queue.
2. Publish the test message again.
3. Confirm the transaction record lands with the correct terminal status.
4. Confirm queue depth returns to zero.
5. Publish the same message again and confirm it's skipped (idempotency).
