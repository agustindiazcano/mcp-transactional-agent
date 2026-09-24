# Public API Abuse Protection: Retries, Rate Limits, and Per-User Limits

**Status:** Analysis, no decision yet (2026-09-24). This document records what protects the public API today, what doesn't, and the options to close the gap. Nothing here is implemented; which option to build, and when, is still open.

---

## 1. Why it matters

The gateway's `POST /api/v1/claims` is public on Cloud Run and has no authentication. Every accepted claim reaches the worker, which calls paid LLMs:

| Step | LLM calls per claim |
|---|---|
| Prompt Guard (Groq) | 1 |
| Policy retrieval (embedding, Vertex) | 1 |
| Double Judge (Judge 1 on Vertex, Judge 2 on Groq) | 2 per attempt |
| Supreme Court, when the judges reject or disagree | 1 per attempt |
| Self-correction attempts (`MAX_LLM_RETRIES`, default 3) | × up to 3 |

A claim that approves on the first try costs 4 calls. A claim that keeps getting rejected costs up to 11 (1 + 1 + 3 × 3). The measured cost of a happy-path claim is ~$0.0004 (see the README's Cost per Transaction), so one claim is cheap. The risk is volume: nothing stops a script from sending claims in a loop, and the demo runs on a free-trial credit.

---

## 2. What protects the API today

| Layer | Protection | Status |
|---|---|---|
| Client retries to the API | A claim's `request_id` is its idempotency key: a duplicate still gets its 202, but it's never processed twice (the `UNIQUE` constraint on `transactions.request_id` plus the worker's lookup before any LLM call). **Caveat:** `request_id` is optional in `ClaimRequest` (`src/api/schemas.py`). If the client leaves it out, the gateway generates a new UUID per request, so a client that retries without sending an id creates a new claim each time. | ✅ with caveat |
| Internal retries | LLM calls retry up to `MAX_LLM_RETRIES`. MCP tool calls use exponential backoff (`MCP_TOOL_MAX_RETRIES`, `MCP_TOOL_BACKOFF_BASE_SECONDS`), with a fresh session per attempt. After the last retry the message is NACKed. | ✅ |
| MCP server (internal) | Phase 1.B boundary: bearer-token authentication, a per-client tool allowlist, argument limits (`REFUND_MAX_AMOUNT`, currency enum, no unknown fields), and a rate limit per client and per tool (`MCP_RATE_LIMIT_PER_MIN`, default 30, sliding 1-minute window counted from the audit table). See [MCP Security Boundary](mcp_security_boundary.md). | ✅ |
| Gateway input validation | `amount` is bounded by `REFUND_MAX_AMOUNT` and `currency` is an enum, so an out-of-range refund fails with a 422 before it's queued. | ✅ |
| Public gateway `POST /api/v1/claims` | No authentication, no limit per IP, no limit per user. | ❌ |
| Cloud Run | `max_instance_count = 2` on the gateway (`infra/cloudrun.tf`). This limits how many gateway instances run at once, not how many claims one client can send. | ⚠️ partial |
| Chatbot for end users | Doesn't exist. Claims are sent as JSON or from the dashboard's ingestion panel. | ❌ |

What does bound the spend today, indirectly: the cloud worker pool runs one instance, which processes one claim at a time. A flood of claims waits in the broker queue instead of calling LLMs in parallel. That limits the spend rate, not the total: the queue keeps draining until it's empty.

---

## 3. Gaps

1. **No limit per IP.** One client can send any number of claims per minute.
2. **No limit per user.** `user_id` comes from the request body, so the caller chooses it. A per-user limit keyed on it could be bypassed by changing the field. A real per-user limit needs an authenticated identity first.
3. **`claim_text` has no length limit.** A long text raises the token count of every LLM call for that claim. A `max_length` on the field is a small, independent fix.
4. **`request_id` is optional.** A client that retries without an id isn't deduplicated (section 2).
5. **The dashboard and the gateway are public.** A login is already on the roadmap (`PENDING.md`, Step 9).

---

## 4. The Front-Desk and chat limits (Phase 1.E)

The Front-Desk in the README (Phase 1.E, designed, not yet implemented) is **UX only** by design:

- It turns the user's free text into a structured JSON payload, or asks a clarifying question.
- It has no access to the database, the knowledge base, or the MCP server, and it never decides an outcome.
- The Back-Office re-validates that JSON server-side; the judges and the deterministic rules decide.
- The Front-Desk only rephrases the final verdict for the user and can't change it.

When it's built, the chat needs its own limits per authenticated user: messages per minute, and a daily token budget. A chatbot is the easiest place to run up LLM spend, because every message is an LLM call even before a claim exists.

---

## 5. Options

| # | Option | What it gives | Cost / trade-off |
|---|---|---|---|
| 1 | `slowapi` in the gateway | A limit per IP (e.g. 10/min and 50/hour) that returns 429. | Free, about 1–2 h with tests. Counts are kept in memory per instance, so with 2 gateway instances the real limit can be up to 2×. On Cloud Run the client IP comes from `X-Forwarded-For`, which the client can also write to: the entry to trust is the one Google's front end appends, not the first one. Verify this against a real Cloud Run request before relying on it. |
| 2 | Per-user limit counted in Postgres (the same pattern as the MCP rate limiter) | Accurate across instances, and ready for Phase 1.E chat users. | Needs an authenticated user identity, so it comes after a login. |
| 3 | Cloud Armor | Rate limiting per IP at Google's edge, plus bot and DDoS rules. | Needs an external HTTPS load balancer in front of Cloud Run, about $18+/month. Too much for the free-trial demo. |
| 4 | Run `demo-down` when not demoing | No exposure at all while the demo is off. | Zero effort. Claims sent while down wait in the broker queue and are processed on the next `demo-up`. |

Independent of the options, a `max_length` on `claim_text` (gap 3) closes the token-amplification path.

---

## 6. Suggested order (not decided)

1. Option 4 now: keep the demo down when it isn't being shown (`scripts/demo-down.ps1`).
2. Option 1 before the next public demo, as a small branch (`feat/gateway-rate-limit`), written test-first (CLAUDE.md §6b): under the limit → 202, over the limit → 429, two IPs counted separately, a spoofed first `X-Forwarded-For` entry doesn't change the count. Add the `claim_text` `max_length` in the same branch.
3. Option 2 together with the dashboard/gateway login and Phase 1.E, keyed on the authenticated user, including the chat's per-user message rate and daily token budget.
4. Option 3 only if the project moves to a paid billing account and the traffic justifies it.

Related: [GCP Infrastructure](../infrastructure/gcp_infrastructure.md) (where the gateway runs and how it's exposed), [MCP Security Boundary](mcp_security_boundary.md) (the internal rate limiter this would mirror).
