---
name: debug-worker
description: >-
  Use this skill when the user reports that messages are being lost, duplicated,
  or stuck in the RabbitMQ queue, or when the worker is failing to ACK/NACK
  correctly. Guides a systematic root-cause investigation.
---

# Worker Debugging Runbook

Use this runbook to diagnose and fix issues in `worker/worker.py` without
breaking the ACK/NACK contract or the idempotency guarantee.

## Step 1 - Confirm the Symptom

Identify which of these failure modes is occurring:

- Messages are consumed but never ACK'd (queue grows, redelivery counter increases).
- Messages are ACK'd but no database record was created (silent failure).
- Messages are processed more than once (idempotency failure).
- Worker crashes with an unhandled exception.
- LLM calls time out and messages are NACK'd but not requeued.

## Step 2 - Check the Idempotency Table

Run this query to see if the request_id was already processed:

```sql
SELECT request_id, status, created_at, updated_at
FROM transactions
WHERE request_id = '<the_request_id>';
```

If the record exists and status is a terminal state (COMPLETED, FAILED,
PENDING_HUMAN_REVIEW), the worker should have short-circuited before
calling the LLM. If it did not, the idempotency check is broken.

## Step 3 - Read the Structured Logs

Worker logs are structured JSON. Filter them for the specific request_id:

```bash
# If logs go to a file
grep '"request_id": "<the_request_id>"' logs/worker.log | python -m json.tool

# If running in Docker
docker logs agentic-worker 2>&1 | grep '<the_request_id>'
```

Look for these log keys: `event`, `request_id`, `error`, `retry_count`, `decision`.

## Step 4 - Inspect the RabbitMQ Management UI

Navigate to the RabbitMQ Management console (default: http://localhost:15672).

Check:
- Queue depth for the main queue and the dead-letter queue.
- Message redelivery count (x-death header).
- Any consumers currently connected.

## Step 5 - Reproduce Locally

Send a test message directly to RabbitMQ:

```python
# scripts/publish_test_message.py
import pika, json, uuid

params = pika.URLParameters("amqp://guest:guest@localhost/")
conn = pika.BlockingConnection(params)
ch = conn.channel()
ch.basic_publish(
    exchange="",
    routing_key="transactions",
    body=json.dumps({
        "request_id": str(uuid.uuid4()),
        "type": "refund",
        "amount": 10.00,
        "user_id": "test-user-1"
    }),
    properties=pika.BasicProperties(content_type="application/json")
)
conn.close()
```

Then watch the worker logs in real time.

## Step 6 - Fix and Verify ACK/NACK Integrity

If you need to modify the ACK/NACK logic:
- NEVER move the ACK before the database commit.
- NEVER swallow exceptions that should trigger a NACK.
- After any fix, run the integration test: `pytest tests/integration/test_worker.py -v`.

## Step 7 - Validate the Fix

After applying the fix:

1. Clear the queue or use a fresh test queue.
2. Publish the test message again.
3. Confirm the transaction record is created with the correct terminal status.
4. Confirm the queue depth returns to zero.
5. Publish the same message again and confirm it is skipped (idempotency).
