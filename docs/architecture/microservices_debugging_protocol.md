# Microservices Debugging Protocol

A general troubleshooting doctrine for this project, not tied to one incident. It exists because following it (late, after a lot of guessing) is what actually resolved the failure documented in [`docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md`](../postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md) — the postmortem is the case study; this document is the reusable rule.

## The core rule: separate the application plane from the transport plane

When two services fail to communicate correctly in a distributed system, there are always at least two independent layers that could be at fault, and they must be tested independently, not simultaneously:

- **The transport plane**: can the two processes reach each other at all? DNS resolution, port binding, TLS/handshake, protocol-level handshakes (like MCP's SSE session setup), authentication/authorization at the connection level.
- **The application plane**: given a working connection, does *this specific application's* control flow, concurrency handling, and business logic behave correctly while using it?

Debugging both at once produces exactly the kind of long, thrashing investigation this project's Phase 1.C MCP postmortem documents: dozens of plausible-sounding hypotheses about networking, Docker, PID 1, signal handling — none of which were the actual cause, because the actual cause was one unguarded line of application code three layers away from the transport at all.

## Rule 1 — Isolate the transport plane before debugging application concurrency

If two containers can't talk to each other, do not start by reading through the application's async/await call graph, its task groups, or its business logic. Rule out the transport first. Concretely:

- Confirm DNS resolution between the two services (`docker exec <container> getent hosts <other-service>` or equivalent).
- Confirm the port is actually listening and reachable (`curl`, `nc`, or a one-line connect script) from *inside* the calling container, using the exact hostname/port the application configuration uses — not `localhost`, not a published host port, the real inter-container address.
- Confirm any auth/handshake layer independently of the application (e.g., this project's MCP transport has its own DNS-rebinding Host-header allowlist, checked in [`docs/postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md`](../postmortems/2026-09-21-phase-1c-load-test-mcp-transport-failure.md) items 1 and 2 — those *were* genuinely transport-layer bugs, found and fixed this way).

Only once the transport plane is confirmed working should application-level concurrency, control flow, or business logic become a suspect.

## Rule 2 — Base-layer verification: inject a minimal script, run it inside the actual container

The single highest-signal debugging step available in a containerized system is not reading code harder — it's writing the smallest possible script that exercises *only* the thing you're unsure about, and running it **inside the actual container**, not against a mock, not against a local process, not against the host's published port (which may not even be routing to the container you think it is — see the port-conflict note below).

```
docker exec <container> python -c "<minimal script>"
# or, for something longer:
cat script.py | docker exec -i <container> python -u -c "import sys; exec(sys.stdin.read())"
```

The decision this produces is binary and immediately actionable:

- **The minimal script passes** → the transport, DNS, dependencies, and credentials are all fine. The problem is in how the *application* uses that transport: exception handling, task/coroutine lifecycle, ordering, or business logic. Stop suspecting infrastructure; start reading the application's actual code path, specifically anywhere an exception could propagate through a context manager that manages background tasks (an `asyncio`/`anyio` `TaskGroup`, an `async with` wrapping a long-lived connection).
- **The minimal script fails** → the problem is infrastructure or a missing dependency: DNS, port/firewall, a package that's imported at the application layer but never made it into the container image, a credential or config value that differs between environments. Don't touch application logic yet.

This is exactly the test that found this project's real bug: a script that only called `sse_client(...)` and `session.initialize()` — nothing else — passed cleanly, every time, inside the real Worker container. That result alone proved the transport, the Host-allowlist fix, the message-path fix, DNS, and the Docker network were all correct. It reduced the remaining search space to "something the application does with that working session" — which led directly to the unguarded `get_llm(provider="groq", ...)` call inside `evaluate_decision()`, three function calls and one `async with` block away from the transport itself.

## Corollary: unit tests mock away the transport plane entirely

This project's unit tests patch `sse_client`, `ClientSession`, and `get_llm` directly (see `tests/unit/test_worker_concurrency.py`). That's correct and necessary for fast, deterministic unit tests — but it means unit tests are structurally blind to two whole categories of bug:

1. **A package imported at the application layer that was never added to `pyproject.toml`'s actual dependencies.** A mocked `get_llm(provider="groq")` never imports `langchain_groq`; the real one does, and only inside a real container (or a real venv) will the `ImportError` actually fire. `mypy`/`ruff`/unit tests all pass cleanly with a missing runtime dependency, because none of them execute the real import path.
2. **How a real exception, raised at a real moment, interacts with real async task-group/cancellation semantics.** A mock that returns a canned value never raises `ImportError` from inside a live `anyio.TaskGroup`, so it can never reproduce the cancellation-cascade failure mode this postmortem documents.

Neither gap is a testing mistake to "fix" by mocking less — mocks exist precisely to make unit tests fast and independent of infrastructure. The correct response is Rule 2: when the mocked test suite is green but the real system isn't, that gap is exactly what a minimal, real, in-container script is for.

## A related, cheap habit: verify declared vs. actual runtime dependencies

Before assuming a code-level bug, it's worth a five-second check: does every `get_llm(provider=X, ...)` (or equivalent optional-provider call) in the codebase have its package declared in `pyproject.toml`? `src/agents/llm_factory.py`'s optional-import pattern (`try: from langchain_X import ... except ImportError: X = None`) is deliberately resilient to a missing package *at import time* — but every call site that actually invokes one of those providers still needs the package installed in whatever environment it runs in, and nothing currently enforces that a `get_llm(provider="groq", ...)` call site has a corresponding `langchain-groq` dependency. This class of gap is invisible to `mypy --strict` (imports guarded by `try/except` type-check fine either way) and to unit tests (mocked). It only surfaces at runtime, in a real environment — which is exactly why Rule 2 matters.

## Port-conflict note

A related, easy-to-miss confound during this project's investigation: running a **native (non-Docker) copy** of a service on the same port a `docker compose`-published container also uses (e.g., `uvicorn src.mcp_server.mcp_server:app --port 8080` on the host, while `agentic_mcp_server` also publishes `8080`) makes `curl localhost:8080`-style "control" tests unreliable — the request may hit either process depending on how the OS resolves the ambiguity. Before trusting a host-side reachability test as a clean signal, confirm nothing else on the host is bound to the same port.
