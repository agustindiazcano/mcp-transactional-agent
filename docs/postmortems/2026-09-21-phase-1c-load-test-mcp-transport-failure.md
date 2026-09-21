# Postmortem: Phase 1.C Load Test — MCP Transport Failures

**Date:** 2026-09-21
**Status:** Two bugs fixed, one open. Phase 1.C's load validation (`PENDING.md` Step 1) is blocked on the open bug.
**Commits:** `4691f17` (fixes), `5e1ab07` (doc corrections)

## Summary

Attempting to run Phase 1.C's Locust load test against the full `docker compose` stack for the first time revealed that "deployment validation: done" — marked done earlier the same day based on HTTP reachability checks (`curl` to `/docs` and `/sse` from the host) — did not mean a real transaction could complete. Every transaction submitted through the containerized stack failed before reaching the point the load test exists to validate (the pessimistic-lock write). Two real, root-caused bugs in the MCP transport configuration were found and fixed. A third failure remains open after extensive isolated testing failed to reproduce it outside the running service.

**Net effect:** the load test has not yet produced a valid reading. No pessimistic-lock behavior under contention has actually been validated in a container environment. `Cost per Transaction` and `System Performance & Telemetry` in README.md remain placeholder values.

## Why this happened: a real gap in prior validation

Phase 1.C's original deployment validation (documented as "done" in the commit that introduced the Dockerfiles) only checked that each service's HTTP surface was reachable — `curl http://localhost:8000/docs`, `curl http://localhost:8080/sse`. It never exercised a full Worker→MCP-server *session* (the actual MCP protocol handshake), because no real transaction had been pushed through the containerized stack end-to-end before today. Unit tests mock the MCP client entirely (`patch("src.worker.worker.sse_client")`), so they couldn't have caught this either. The gap was structural, not a testing oversight in one place — nothing in the test suite or prior validation exercised "a real container talking MCP to another real container."

## Timeline

1. **First Locust run** (worker's `LLM_PROVIDER` overridden to `mock` via a temporary `docker-compose.override.yml`, to avoid spending real API credits on a concurrency test): 2106 requests, 0 HTTP failures, but latency climbed steadily through the run (P50 390ms → 597ms). Traced to `src/api/main.py` opening a brand-new `aio_pika.connect_robust()` connection per request instead of reusing one. **Not fixed** — documented in `PENDING.md`.
2. **Checked the Worker logs**: every single message failed with `relation "transactions" does not exist`. The `knowledge_base`/`transactions` tables were gone, but `alembic_version` still reported the migration as applied. Root cause: `tests/integration/test_knowledge_base_repository.py`'s teardown fixture runs `Base.metadata.drop_all()`, which drops *every* table on `Base` — including `transactions` — and that test had last run at the end of the previous session without a follow-up `alembic upgrade head`. Fixed by a full volume reset (`docker compose down -v`) and re-migrating from scratch. This is a latent footgun in the test suite, not something fixed today — running that integration test locally silently breaks the dev database for anything else until migrations are re-applied. Worth a proper fix later (e.g., the fixture re-running migrations instead of `drop_all`, or the integration suite using a separate database).
3. **Second Locust run** (schema fixed): 1827 requests, 0 HTTP failures, but the Worker crashed on **every** message with two distinct errors:
   - `prompt_guard.py`'s "Failed to run prompt guard, failing open" — root cause: `prompt_guard.py` explicitly calls `get_llm(provider="groq", ...)`, hardcoded, ignoring `LLM_PROVIDER=mock` entirely. `langchain-groq` isn't in `pyproject.toml`'s dependencies, so this `ImportError`s inside the container every time. Caught by its own fail-open handler, so **not blocking** — but it means Judge 2 (Groq) cannot actually run in the Docker deployment as currently packaged, and it proved the `mock` override doesn't fully prevent real-provider code paths from being attempted. **Not fixed** — documented in `PENDING.md`.
   - `httpx2.HTTPStatusError: Redirect response '421 Misdirected Request'` / server logs showing `ValueError: Request validation failed` inside `mcp/server/sse.py`'s `connect_sse` — the actual blocker.
4. **Root-caused the 421**: the MCP SDK's `MCPServer.sse_app()` defaults `allowed_hosts` (DNS-rebinding protection) to `["127.0.0.1:*", "localhost:*", "[::1]:*"]`. `curl http://localhost:8080` passed because `Host: localhost` matched; the Worker connects via the Docker Compose service name (`Host: mcp_server:8080`), which didn't. **Fixed**: extended (not disabled) the allowlist in `src/mcp_server/mcp_server.py` to include `mcp_server:*`.
5. Rebuilt `mcp_server`, retested — hit a **build-cache staleness issue**: `docker compose up -d --build mcp_server` did not actually pick up the code change (verified by `docker exec`-ing into the container and `cat`-ing the file — it had my Host-allowlist fix but not later edits). Resolved with `docker compose build --no-cache mcp_server` + `--force-recreate`. Worth remembering: `--build` is not always sufficient to guarantee a fresh layer in this environment.
6. **After the real fix landed**: 8 transactions reached `COMPLETED`, 7 reached `PENDING_HUMAN_REVIEW` — proof the Host-allowlist fix was correct and the full pipeline *can* complete. But a new error appeared: `httpx2.HTTPStatusError: Redirect response '307 Temporary Redirect'` for `POST /message?session_id=...`.
7. **Root-caused the 307**: `message_path="/message"` (singular, no trailing slash) was passed to `mcp.sse_app()`. Starlette's `Mount` registers routes as `<path>/<rest>`; a bare request to the mount path without a trailing slash triggers a redirect, which the MCP client's `httpx` client does not follow by default. **Fixed**: changed to `"/messages/"` (also the MCP SDK's own default).
8. **Next failure, still present today**: `httpx2.RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read)`, raised while the client is mid-read of the SSE stream awaiting the `initialize()` response. Server-side logs show no error at all for that connection — `GET /sse` → `200 OK`, both `POST /messages/` → `202 Accepted`, then nothing.
9. **Extensive isolated reproduction attempts, all unsuccessful** (see "What We Ruled Out" below) — every controlled test succeeded; only the actual running Worker service failed, almost every time.
10. **Found and fixed a real, related bug along the way**: no RabbitMQ prefetch limit on the Worker's channel (`channel.set_qos()` was never called), so RabbitMQ pushed the *entire* queue backlog into the Worker's local buffer on every (re)connect, regardless of how fast `process_message()` actually drains it. This is why every attempt to get a "clean" single-message test kept getting swamped by hundreds of old messages. **Fixed**: `channel.set_qos(prefetch_count=1)`.
11. **Found the Recovery Sweeper was actively working against the debugging effort** (not a bug — working exactly as designed): thousands of transactions stuck in `PROCESSING` from the earlier failed runs were being detected as "zombies" and re-published to the queue every sweep, which is precisely what `recovery_sweeper.py` is supposed to do. It just meant `purge_queue` never stayed empty until the sweeper was stopped too and the stuck rows were cleared.
12. **Even with a fully clean environment** (sweeper stopped, prefetch=1, zero backlog, single test message, fresh container restart), a real transaction through the actual `worker` container **still failed** with the same `RemoteProtocolError`. Root cause not found. Stopped here and cleaned up the environment (see "What Was Left Running" below — nothing; everything was torn down).

## Root Causes Found and Fixed

| # | Symptom | Root Cause | Fix | Status |
|---|---|---|---|---|
| 1 | Every Worker→MCP request: `421 Invalid Host header` | MCP SDK's DNS-rebinding protection defaults `allowed_hosts` to loopback-only; Docker Compose service name (`mcp_server:8080`) isn't loopback | Extended `allowed_hosts`/`allowed_origins` in `src/mcp_server/mcp_server.py` to include `mcp_server:*` | Fixed, `4691f17` |
| 2 | Every message POST: `307 Temporary Redirect`, not followed by the client | `message_path="/message"` (no trailing slash) vs. Starlette `Mount`'s `<path>/<rest>` routing | Changed to `"/messages/"` (SDK default) | Fixed, `4691f17` |
| 3 | Restarted Worker instantly flooded with the entire historical backlog, making clean re-testing impossible | No `prefetch_count` set on the Worker's RabbitMQ channel | `channel.set_qos(prefetch_count=1)` | Fixed, `4691f17` |
| 4 | Every message: `relation "transactions" does not exist` (session-specific, not a code bug) | Integration test's `Base.metadata.drop_all()` teardown had wiped the dev DB schema without a corresponding `alembic upgrade head` | Full volume reset + re-migrate | Resolved for this session; the underlying test-hygiene gap is not fixed |

## Root Cause NOT Found (Open)

**Symptom:** `httpx2.RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read)`, raised client-side while awaiting the SSE-delivered response to `mcp_session.initialize()`. No corresponding error appears in the MCP server's logs for that connection.

**Confirmed:** only the Worker container's actual entrypoint process (`CMD ["python", "-m", "src.worker.worker"]`, running as the container's PID 1) exhibits this failure. It failed on a freshly restarted container's very first message, with zero backlog, prefetch limited to 1, and the Recovery Sweeper stopped — ruling out every environmental confound found along the way.

**Leading hypothesis, not yet tested:** PID-1-specific signal handling. A process running as PID 1 in a container with no init system does not get the kernel's normal default signal dispositions (notably around `SIGPIPE`/child reaping), which is a well-known class of Docker bugs. Docker Compose has a built-in fix for exactly this: setting `init: true` on a service runs a minimal init (tini) as PID 1 ahead of the application, restoring normal signal handling. This was identified as the most promising next step but **not tried** — this postmortem was written instead of continuing to debug further, per explicit direction to stop and document rather than keep going indefinitely.

## What We Ruled Out

Every one of the following was tested in isolation and **succeeded** (did not reproduce the failure), narrowing the problem down to something specific about the real, long-running entrypoint process rather than the MCP protocol exchange itself:

- A single MCP session, opened and closed immediately (`docker exec` one-shot script).
- The same, with the session held open for ~1s of simulated work before closing.
- 20 sequential MCP sessions in a loop within one process.
- 20 concurrent MCP sessions (`asyncio.gather`).
- 20 sequential MCP sessions while Locust simultaneously hammered the Gateway with 100 concurrent users (ruled out general system/Docker resource contention).
- An MCP session opened alongside a real, concurrently-active `aio_pika.connect_robust()` RabbitMQ connection.
- The exact `queue.iterator()` + `async with message.process(ignore_processed=True)` consumption pattern `start_worker()` uses, processing 15 real messages from a real queue in one long-lived process.
- Running the unmodified `src.worker.worker` module via `docker exec` inside the *same* running container (same image, same network, same environment variables — verified `MCP_SERVER_URL` resolves identically) instead of as the container's entrypoint.

None of these reproduced the failure. The real, `docker compose up`-started `worker` service fails on nearly every attempt.

## Impact on the Roadmap

- `PENDING.md` Step 1 (Locust load test) is **blocked** on the open MCP bug, not just "not yet run." Re-attempting it before the root cause is fixed would produce the same result.
- README.md's Phase 1.C section and roadmap table were corrected from "deployment validation: done" to explicitly distinguish HTTP reachability (verified) from a working transaction (not yet reliable) — see `5e1ab07`.
- `Cost per Transaction` and `System Performance & Telemetry` tables remain placeholders; they depend on Step 1/Step 2 completing, which depend on this bug being fixed.

## Recommended Next Steps

1. **Try `init: true`** on the `worker` service (and, for consistency, the other app services) in `docker-compose.yml` first — cheap, well-understood, directly targets the one confirmed differentiator (PID-1-ness) between every failing case and every succeeding case.
2. If that doesn't resolve it, capture a packet trace (`tcpdump` inside the container, or Wireshark against the Docker bridge network) during a real failure to see whether the TCP connection is actually reset by the peer or whether this is purely an application-layer read timing issue.
3. Enable debug-level logging on both `mcp.client.sse` and `uvicorn.error`/`uvicorn.access` for a real failing run to capture more server-side detail than is currently logged.
4. Consider whether pinning specific `mcp`/`httpx`/`uvicorn` versions (rather than floating latest via `pip install .`) changes the behavior — this environment's exact resolved versions were never recorded.
5. Fix the two smaller findings regardless of the above: add `langchain-groq` to dependencies (or stop hardcoding `provider="groq"` in `prompt_guard.py` and respect `LLM_PROVIDER`), and give `src/api/main.py` a reused, pooled AMQP connection instead of one per request.
6. Fix the integration-test teardown footgun (`Base.metadata.drop_all()` silently desyncing the dev DB from `alembic_version`) before it costs someone else the same hour of confusion it cost this session.
