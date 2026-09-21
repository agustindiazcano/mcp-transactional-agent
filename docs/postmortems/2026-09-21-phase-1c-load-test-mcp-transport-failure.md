# Postmortem: Phase 1.C Load Test — MCP Transport Failures

**Date:** 2026-09-21
**Status:** Three MCP-adjacent bugs found. Two fixed and verified (`4691f17`). The third — the one that actually blocked every transaction — has been **root-caused** by a parallel debugging session; the fix is proposed but **not yet applied or verified** in this repository. Phase 1.C's load validation (`PENDING.md` Step 1) remains blocked until it is.
**Commits:** `4691f17` (fixes to date), `5e1ab07` (doc corrections)

## Summary

Attempting to run Phase 1.C's Locust load test against the full `docker compose` stack for the first time revealed that "deployment validation: done" — marked done earlier the same day based on HTTP reachability checks (`curl` to `/docs` and `/sse` from the host) — did not mean a real transaction could complete. Every transaction submitted through the containerized stack failed before reaching the point the load test exists to validate (the pessimistic-lock write). Two real, root-caused bugs in the MCP transport configuration were found and fixed by this session. A third failure resisted this session's own extensive isolated reproduction attempts entirely; it was subsequently root-caused by a **separate, parallel debugging session** using container-level isolation testing (see "Root Cause: Found" below) — a synchronous `ImportError` inside a guardrail call, raised while inside an `async with`-managed MCP session, that anyio's `TaskGroup` reports as a generic transport failure. That diagnosis is documented here for the record; this session did not independently apply or re-verify the proposed fix.

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
| 5 | Every real transaction: `TaskGroup (1 sub-exception)` / `RemoteProtocolError` — **the actual blocker this whole postmortem is about** | `evaluate_decision()` (`src/agents/judge.py`) calls `get_llm(provider="groq", ...)` unguarded; `langchain-groq` isn't a declared dependency, so it `ImportError`s inside the MCP session's task group on every call, which anyio reports as a generic transport failure | Add `langchain-groq` to `pyproject.toml` (proposed) | **Diagnosed, not yet applied/verified** — see "Root Cause: Found" below |

## Root Cause: Found (by a parallel debugging session)

**Symptom:** `httpx2.RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read)`, raised client-side while awaiting the SSE-delivered response to `mcp_session.initialize()`. No corresponding error appears in the MCP server's logs for that connection. This session's `init: true` (PID-1 signal handling) hypothesis, recorded in an earlier version of this document as the leading candidate, was **not the cause** — it was never tested, and the actual explanation is unrelated to PID 1 or Docker networking entirely.

**The actual cause:** `src/agents/judge.py`'s `evaluate_decision()` calls `get_llm(provider="groq", temperature=0.0)` to construct Judge 2, unconditionally and with no `try/except` around the call:

```python
judge1_gemini = get_llm(provider="gemini", temperature=0.0)
judge2_groq = get_llm(provider="groq", temperature=0.0)   # <- raises here, uncaught
```

`langchain-groq` is not in `pyproject.toml`'s dependencies (see `src/agents/prompt_guard.py`'s already-documented, separately-caught instance of the same gap). Inside `get_llm()`, that means `ChatGroq is None`, and the `"groq"` branch does `raise ImportError("langchain-groq is not installed")`. `prompt_guard.py` catches its own copy of this exact error and fails open, which is why that particular symptom never blocked anything. `evaluate_decision()` has no equivalent guard — the `ImportError` propagates straight out of it.

`evaluate_decision()` is `await`ed from inside `src/worker/worker.py`'s `while retries < max_retries:` loop, which is itself inside `async with sse_client(...) as streams, ClientSession(...) as mcp_session:`. `sse_client` is implemented (`mcp/client/sse.py`) as an `@asynccontextmanager` wrapping `anyio.create_task_group()`, with two background tasks (`sse_reader`, `post_writer`) running concurrently with whatever code executes inside the `async with` block. When `evaluate_decision()`'s `ImportError` propagates up through that block, it is thrown back into the `sse_client` generator at its `yield` point — inside its own task group — which triggers the task group's standard behavior on an exception: cancel the still-running background tasks and collect whatever they raise. Cancelling `sse_reader` mid-read of the open SSE HTTP response is what produces the `RemoteProtocolError: peer closed connection` — a real symptom, but a *side effect* of the cancellation, not evidence of an actual network or transport problem. anyio bundles the original `ImportError` and/or the cancellation-driven error into an `ExceptionGroup`, which is exactly what `str()`s down to the generic message this session spent so long chasing: `"unhandled errors in a TaskGroup (1 sub-exception)"`. The real cause was never visible in that message because Python's default logging of an `ExceptionGroup` via `logger.error(f"...{e}")` (a plain `str()`, not `logger.exception(...)`) doesn't print the wrapped traceback.

**This fully explains why this session's isolated reproduction attempts never reproduced it** (see "What We Ruled Out" below): none of those probe scripts ever called `evaluate_decision()` — they only tested `sse_client`/`ClientSession.initialize()` in isolation, so the one line that triggers the failure was never exercised. It also explains why fixing it requires no changes to networking, Docker, or the MCP transport configuration at all.

**How it was actually found:** by writing a minimal, synchronous/async test script and running it *directly inside the already-running Worker container* to isolate connectivity/dependency verification from the application's own concurrency and control flow — deliberately separating "does the transport layer work" from "does the application's use of it work." That script proved the container *could* connect, `initialize()`, and list tools cleanly in isolation (the same conclusion this session's own probes reached, independently, via a similar technique). With the transport cleared, the remaining suspect was the application code path itself, which is what led to inspecting `evaluate_decision()` directly rather than the transport once more. This is now documented as a general practice — see [`docs/architecture/microservices_debugging_protocol.md`](../architecture/microservices_debugging_protocol.md).

**Proposed fix (not yet applied in this repository):**
1. Add `langchain-groq` to `pyproject.toml`'s `dependencies`.
2. Rebuild the `worker` image and retest a real transaction end-to-end.
3. Also revert the temporary `traceback.print_exception(...)` block added to `worker.py`'s outer exception handler during this investigation, once the fix is confirmed — it was a debugging aid, not intended to stay.

This session did not apply or verify this fix; it only documents the diagnosis and the proposed change for whoever applies it next.

## What We Ruled Out

Every one of the following was tested in isolation and **succeeded** (did not reproduce the failure). At the time, this narrowed the problem down to something specific about the real, long-running entrypoint process — which turned out to be the wrong axis entirely. The actual differentiator (see "Root Cause: Found" above) is that none of these ever called `evaluate_decision()`, the one code path that triggers the failure:

- A single MCP session, opened and closed immediately (`docker exec` one-shot script).
- The same, with the session held open for ~1s of simulated work before closing.
- 20 sequential MCP sessions in a loop within one process.
- 20 concurrent MCP sessions (`asyncio.gather`).
- 20 sequential MCP sessions while Locust simultaneously hammered the Gateway with 100 concurrent users (ruled out general system/Docker resource contention).
- An MCP session opened alongside a real, concurrently-active `aio_pika.connect_robust()` RabbitMQ connection.
- The exact `queue.iterator()` + `async with message.process(ignore_processed=True)` consumption pattern `start_worker()` uses, processing 15 real messages from a real queue in one long-lived process.
- Running the unmodified `src.worker.worker` module via `docker exec` inside the *same* running container (same image, same network, same environment variables — verified `MCP_SERVER_URL` resolves identically) instead of as the container's entrypoint.

None of these reproduced the failure. The real, `docker compose up`-started `worker` service fails on nearly every attempt — because, unlike every probe above, `process_message()` always reaches `evaluate_decision()`.

## Impact on the Roadmap

- `PENDING.md` Step 1 (Locust load test) is **blocked** on the open MCP bug, not just "not yet run." Re-attempting it before the root cause is fixed would produce the same result.
- README.md's Phase 1.C section and roadmap table were corrected from "deployment validation: done" to explicitly distinguish HTTP reachability (verified) from a working transaction (not yet reliable) — see `5e1ab07`.
- `Cost per Transaction` and `System Performance & Telemetry` tables remain placeholders; they depend on Step 1/Step 2 completing, which depend on this bug being fixed.

## Recommended Next Steps

1. **Apply and verify the proposed fix**: add `langchain-groq` to `pyproject.toml`'s dependencies, rebuild the `worker` image, and send a real transaction through the full containerized stack. Confirm it reaches `COMPLETED` or `PENDING_HUMAN_REVIEW` cleanly, with no `TaskGroup`/`RemoteProtocolError` in the logs. This is the one item that actually closes out this postmortem.
2. Revert the temporary `traceback.print_exception(...)` debug block in `worker.py`'s outer exception handler once the fix is verified.
3. **Decide deliberately** whether `evaluate_decision()`'s Groq dependency should be a hard requirement (add the package) or should degrade like `prompt_guard.py` does (wrap the `get_llm(provider="groq", ...)` call and fall back / fail open) — right now this is the *only* place in the codebase where a missing optional-provider package can silently take down an entire in-flight transaction instead of degrading. Worth a general rule: every `get_llm(provider=X, ...)` call site outside `llm_factory.py` itself should either declare `X`'s package as a hard dependency, or explicitly handle its absence the way `prompt_guard.py` already does.
4. Re-run Phase 1.C's Step 1 Locust load test once the above is verified — this is the actual blocker that's been in the way since this postmortem started.
5. Fix the Gateway's per-request AMQP connection (`src/api/main.py`) — a reused, pooled connection instead of one per request.
6. Fix the integration-test teardown footgun (`Base.metadata.drop_all()` silently desyncing the dev DB from `alembic_version`) before it costs someone else the same hour of confusion it cost this session.
