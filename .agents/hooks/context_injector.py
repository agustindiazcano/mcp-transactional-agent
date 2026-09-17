#!/usr/bin/env python3
"""
context_injector.py

PreInvocation hook: injects a concise architecture reminder into the agent's
context before each model call. This keeps critical constraints visible even
in long conversations where the GEMINI.md content may be far back in the
context window.

Reads a JSON payload from stdin. Writes an injectSteps payload to stdout.
"""

import json
import sys

REMINDER = """
[Architecture Reminder - agentic-mcp-engine]

Before proposing or writing any code, verify the following invariants:

1. Layer isolation: routers/ -> services/ -> repositories/. Never skip layers.
2. agents/ must not import from repositories/ or models.py directly.
3. Every I/O function must be async.
4. Secrets and config must use pydantic-settings and environment variables.
5. The LLM must only interact with external state through MCP tool calls.
6. Idempotency check (request_id lookup) must happen before any LLM call in worker.py.
7. Destructive SQL must always include a WHERE clause. Confirm with the user before dropping schema objects.
8. Use structlog for all logging. Never use print().
9. Every new module must have a corresponding test file under tests/.
10. When the LLM-as-a-Judge returns REJECT, set status to PENDING_HUMAN_REVIEW and log the reason.
""".strip()


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"injectSteps": []}))
        return

    invocation_num = payload.get("invocationNum", 0)

    # Inject the reminder on the first invocation and every 5th thereafter
    # to avoid flooding the context window in short tasks
    if invocation_num == 0 or invocation_num % 5 == 0:
        inject = [{"ephemeralMessage": REMINDER}]
    else:
        inject = []

    print(json.dumps({"injectSteps": inject}))


if __name__ == "__main__":
    main()
