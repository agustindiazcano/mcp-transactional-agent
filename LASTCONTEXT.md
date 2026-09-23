# Last Context — Pending Work, Agents, and Tools Review (2026-09-22)

Before the list, an important finding that came up while reviewing this.

## ⚠️ Finding: no tool is executed today
The worker opens an MCP session (`initialize()`) but **never calls a tool**: there is no `call_tool` anywhere in `src/`. When the judges approve, the worker marks the transaction `COMPLETED` and stops there: **the refund never goes through the MCP server**. On top of that, both tools are stubs: `execute_refund` returns a string and `validate_fraud_score` always returns `0.12`.

The MCP security boundary is real and tested, but nothing in the actual pipeline passes through it. This is the first gap to close, before any new agent.

---

## 1. What was still pending

**Immediate**
- Commit and PR for step 2 (`fix/judge-untrusted-input`), and merge the Judge 2 docs PR (`docs/judge2-model-name`).
- **New:** wire up real execution, i.e. the worker calls `execute_refund` via MCP after approval. This touches `worker.py`; per CLAUDE.md §8, confirm before changing the flow near the ACK/NACK logic.

**Roadmap phases**
- **Phase 1.E:** real primary agent + Front-Desk. This is next.
- **Phase 1.F:** choose each judge's provider per request.
- **Phase 2:** deterministic rule base. It is the defense that can't be prompt-injected, because it doesn't read natural language.
- **Phase 3:** drift detection. **Phase 5:** comparison against an MLP. **Phase 6:** Google Cloud (in progress).
- **PENDING Step 3:** promptfoo, TruLens/Ragas, and Langfuse (none of them implemented).

**Small findings**
- Gemini ignores `temperature=0`, so Judge 1 and the Supreme Court are not deterministic.
- `langchain-google-vertexai` is not declared, and the Vertex branch uses an old model (`gemini-1.5-pro`).
- The BLE001 in `judge.py` remains, and `test_transaction_repository.py` is misplaced (it needs a DB).
- Known Phase 1.B limitations:
  - `tools/list` isn't filtered by identity: a client can see a tool's name even if it can't call it.
  - The audit log's `result` field only records "invoked", not whether the tool succeeded or failed.
  - There is no DB role that allows only INSERT on the audit table.
- The dashboard doesn't show which policy chunk was used (the RAG detail view).

---

## 2. What does it mean for a judge to be agentic?

An **agent** is an LLM inside a loop: it observes, **decides on its own** which tool to call, looks at the result, and repeats until the goal is met. An agentic judge could, for example, call `get_order()` to verify that the requested amount matches the real purchase, instead of trusting the arguments.

| | Agentic judge | One-shot judge (current) |
|---|---|---|
| Verifies facts | ✅ fetches them itself | ❌ only evaluates what it's given |
| Attack surface | ❌ injected text can influence which tools it calls | ✅ has no tools |
| Determinism, cost, and latency | ❌ multiple steps, variable | ✅ one call |
| Independence | ❌ increasingly resembles the actor it evaluates | ✅ only verifies |

**Recommendation: a middle ground.** **Deterministic code** fetches the evidence (order, history, fraud score) before judging and injects it into the judge's `<reference_context>`, the same way RAG already works. That way the judge verifies against real facts but stays one-shot and can't be injected through that path. Autonomy belongs to the agent that **proposes**, not the one that **checks**.

---

## 3. Which agents can we add? Are they the same one or different ones?

**They are different.** Each role is a separate agent, with its own prompt, its own permissions, and **its own `client_id` on the MCP server**, with its own tool allowlist. The Phase 1.B boundary is already built for this: `mcp_clients.json` supports multiple clients.

| # | Agent | What it does | Tools | Risk | Was it in the docs? |
|---|---|---|---|---|---|
| A | **Front-Desk** (talks to the user) | Converses, builds the intent JSON, asks when a field is missing, and phrases the reply from the verdict | No MCP tools. Only `submit_claim` and `get_claim_status` (its own claims) via the API | Low | ✅ **Yes**, Phase 1.E |
| B | **Resolver** (the autonomous back-office agent) | Investigates in several steps: order, history, fraud, policy. Then **proposes** full refund, partial refund, denial, or escalation | Read-only: `get_order`, `get_refund_history`, `validate_fraud_score`, `search_policy` | Medium | ⚠️ **No.** The Phase 1.E doc says the back-office is deterministic. This is a new decision |
| C | **Fraud Analyst** | For flagged cases: investigates and writes a report for the human reviewer | Read-only | Low | No |
| D | **Human-reviewer copilot** | Summarizes the full trail (guard, judges, evidence) of each `PENDING_HUMAN_REVIEW` case | Read-only | Low | No |
| E | Policy curator | Maintains the RAG knowledge base | **Writes** to the KB | **High**: it's the indirect-injection path | No, later |

**Key principle:** no agent executes writes. The Resolver **proposes**; the judges and the rule base **approve**; **deterministic code** calls `execute_refund`. The LLM never pushes the button.

---

## 4. Tools we would have

| Tool | Type | Who can use it | Note |
|---|---|---|---|
| `get_order(order_id)` | Read | Resolver, Analyst, evidence code | Needs an `orders` table with sample data. Enables the "refund exceeds the original amount" check that CLAUDE.md §10 requires and that can't be verified today |
| `get_user_history(user_id)` | Read | Resolver, Analyst | Was in CLAUDE.md's original step 3 and was never implemented |
| `get_refund_history(user_id)` | Read | Resolver, Analyst | Feeds fraud scoring and the refunds-per-month limit |
| `validate_fraud_score(user_id)` | Read | Resolver, evidence code | Returns a fixed 0.12 today; would be computed from real rules |
| `search_policy(query)` | Read | Resolver | RAG as a tool, so the agent can look up the policy it needs |
| `execute_refund(...)` | **Write** | **Worker only**, after approval | Idempotent by `request_id`: a retry can't refund twice |
| `issue_store_credit(...)` | Write | Worker only | Alternative to a refund |
| `escalate_to_human(reason)` | Write | Worker only | Today it's just a status in the table |
| `notify_user(message)` | Write | Front-Desk, via the worker | Closes the loop with the user |

---

## 5. "One LLM answers the user and the others work behind the scenes": was this planned?

**Yes.** It is exactly Phase 1.E Front-Desk / Back-Office: it's in CLAUDE.md §5a-iv, the README, and PENDING Step 5. It includes the verdict contract (`REJECTED: <objective reason>`), which keeps the judges' internal reasoning from reaching the user. **It is not implemented.**

The doc does **not** cover how the answer reaches the user, since the back-office is asynchronous and returns 202. It needs:
- a chat endpoint,
- conversation state,
- the Front-Desk saying "received, reviewing it",
- and a notification mechanism: polling the status, SSE, or a chat in the dashboard.

---

## 6. Proposed order, to evaluate

1. **Close step 2** (commit and PR).
2. **Real execution:** the worker calls `execute_refund` via MCP, the read tools stop being stubs (an `orders` table with sample data), and the evidence is injected into the judges. *Closes the ⚠️ gap and gives the judges facts to verify.*
3. **Resolver (agent B):** a tool-calling loop with read-only tools. *This is what backs "built autonomous AI agents".*
4. **Front-Desk (agent A):** chat, verdict contract, and the reply to the user. *Completes the end-to-end experience.*
5. Afterwards: the Phase 2 rule base, and agents C and D.

Two decisions are needed to move forward:
- **Do we add the Resolver (agent B)?** It changes the documented Phase 1.E design, where the back-office is deterministic. Recommendation: yes, because it's the real agentic piece, and deterministic control stays the same across judges, rule base, and execution.
- **Do we start with step 2 of this order, real execution?** It touches `worker.py`, which is why confirmation is needed first.

---

# Update — Pending Work by Priority and Recommendation (2026-09-22)

Step 2 (judges treat user text as data + visible guard fail-open) and this document were committed together in `f1fb849` on `fix/judge-untrusted-input`. That branch also includes the Judge 2 docs commit (`6783c7b`).

## Pending, by priority

**🔴 Critical: the system claims something it doesn't do**
1. **Real execution doesn't exist.** The worker never calls an MCP tool: it marks `COMPLETED` without executing the refund, and the tools are stubs.

**🟠 High: what backs "autonomous AI agents"**

2. **Real read tools:** `get_order` (with a sample `orders` table), `get_refund_history`, and `validate_fraud_score` with a real calculation. With those, the evidence can be injected into the judges.
3. **Resolver (agent B):** a tool-calling loop with read-only tools that proposes the action. It's a design decision the user has to make.
4. **Front-Desk (agent A):** chat with the user, verdict contract, and how the answer reaches them (polling or SSE).

**🟡 Medium**

5. **Phase 2, rule base:** the only defense that can't be prompt-injected, and CLAUDE.md §10 requires it for `execute_refund`.
6. **Gemini ignores `temperature=0`:** either fix the docs or switch models, and measure how stable the verdicts are.
7. **PENDING Step 3:** promptfoo (a labeled case set to measure the judges) and Langfuse.
8. **Phase 6 GCP:** declare `langchain-google-vertexai`, update the Vertex model, and deploy to Cloud Run.

**🟢 Low**

9. Phase 1.F (provider per judge), the BLE001 in `judge.py`, moving `test_transaction_repository.py` to integration, the RAG view in the dashboard, and the known Phase 1.B limitations.
10. Phases 3 and 5, and agents C and D.

## Recommendation

**Follow the order 1 → 2 → 3 → 4.**
- **1 and 2 first.** Today the pipeline approves refunds that are never executed, and the judges evaluate without facts. Building an agent on top of that would stack autonomy on a base that doesn't yet do what it says.
- **Then the Resolver.** It's the piece that turns "orchestration around LLMs" into "autonomous agent" with code to back it, and the controls will already be solid: guard, hardened judges, and deterministic execution.
- **The Front-Desk last.** It's the most visible part for a demo, but it depends on the back-office actually resolving cases.

Starting item 1 needs the user's OK: it touches `worker.py` near the ACK/NACK flow (CLAUDE.md §8). The plan is that, after approval, the worker calls `execute_refund` via MCP with `request_id` as the idempotency key. If the tool fails, it retries and, once retries are exhausted, NACKs the message.


---

# Update — Step 1 Done: Real Refund Execution (2026-09-22)

Branch `feat/real-refund-execution`. **Not committed and no PR yet**, by the user's instruction.

## Result
The 🔴 critical gap is closed. When the judges approve, the worker now actually executes the refund through the MCP server. Before, it only marked the transaction `COMPLETED`.

## Decisions (approved by the user before starting)
- `ClaimRequest` gains optional `order_id`, `amount`, and `currency` fields.
- `execute_refund` changes contract (approved):
  - It takes `request_id` as its idempotency key, backed by a `refunds` table with a unique `request_id`.
  - It returns a dict instead of a string.
- If `execute_refund` still fails after every retry, the status becomes `EXECUTION_FAILED` and the message is NACKed with `nack(requeue=False)`. This ACK/NACK change was approved.
- **Design:** MCP SDK 2.2.0 hangs in `call_tool` when the middleware rejects a call with a 4xx. So each attempt opens a fresh session with `ClientSession(read_timeout_seconds=MCP_TOOL_TIMEOUT_SECONDS)` and retries with exponential backoff, in `src/worker/refund_executor.py`.
- Remove the unused MCP session around the judges, and move `Currency` to `src/core/`.
- Work test-first (red tests before any code).
- Migration: the dev DB already had an empty `refunds` table, created by `test_transaction_repository.py`'s `create_all`. The user chose to drop it and run `alembic upgrade head`.

## Decision I made (flag for review)
An **approved claim without `order_id`/`amount`** now goes to `PENDING_HUMAN_REVIEW`, not `COMPLETED`, because there is nothing to execute. Marking it complete would repeat the original gap. The trail records it as `execution: {"status": "not_executable"}`.

## What changed
- **`src/core/currency.py`:** the `Currency` enum, shared by the gateway and the MCP schemas.
- **`src/api/schemas.py`:** `ClaimRequest` gains optional `order_id`, `amount`, and `currency`. When present, they are validated at the gateway with the same limits as the MCP boundary (`0 < amount <= REFUND_MAX_AMOUNT`, currency enum). An out-of-bounds refund fails with a 422 at ingestion, not after the judges approve it.
- **`src/core/models.py`:** new `Refund` model, a ledger with `UNIQUE(request_id)` and a `Numeric(12,2)` amount. It has no foreign key to `transactions`, because the MCP server owns this ledger.
- **Migration `b3e1f0c9a2d4`:** creates the `refunds` table. It is applied to the dev DB (`622b710f2855` → `b3e1f0c9a2d4`).
- **`src/core/repositories/refund_repository.py`:** `record_refund()` uses `INSERT ... ON CONFLICT DO NOTHING` and returns `(refund, created)`. A replay returns the stored row, even if its arguments differ.
- **`src/mcp_server/mcp_server.py`:** `execute_refund(request_id, transaction_id, amount, currency)` is async and real. It returns `{status: executed | already_executed, refund_id, request_id, transaction_id, amount, currency}`. `create_app()` sets the session maker the tools use.
- **`src/mcp_server/tools/schemas.py`:** `ExecuteRefundArgs` requires a non-empty `request_id`.
- **`src/worker/refund_executor.py`:**
  - `execute_refund_via_mcp()` and `McpCallPolicy.from_settings()`.
  - A fresh session per attempt, with a read timeout and exponential backoff.
  - A tool error result or a missing structured result counts as a failed attempt.
  - It raises `RefundExecutionError`, whose message names the real cause, unwrapped from anyio's `ExceptionGroup`.
- **`src/worker/worker.py`:**
  - Removed the unused MCP session around the judges.
  - The new step 4 is deterministic execution after APPROVE. The status is `COMPLETED`, `PENDING_HUMAN_REVIEW` (not executable), or `EXECUTION_FAILED` followed by `nack(requeue=False)`.
  - The tool result goes into `judge_trail["execution"]`.
- **`src/core/config.py`:** new `MCP_TOOL_TIMEOUT_SECONDS` (10), `MCP_TOOL_MAX_RETRIES` (3), and `MCP_TOOL_BACKOFF_BASE_SECONDS` (1.0), documented in README, CLAUDE.md §9, and `.env.example`.
- **`src/ui/theme.py`:** `EXECUTION_FAILED` is an alert (red) status.
- **Docs:** README updated (build sequence step 11, operational contract, MCP server section, test counts, project structure, known limitations). CLAUDE.md, GEMINI.md, and AGENTS.md updated identically:
  - a new §4 directive, "Only Deterministic Code Executes Write Tools";
  - the SDK 2.2.0 hang note;
  - §5a step 10;
  - §5a-i item 3;
  - the §7 layout;
  - the §9 env vars.

## Validation
- **Tests:** 152/152 pass (117 unit + 35 integration), with 83% line coverage over `src/`.
- **Lint and types:** `ruff` and `mypy --strict` are clean except for two errors that predate this branch: the BLE001 in `judge.py` and an unused `type: ignore` in `llm_factory.py`.
- **Live check against a real MCP server** running the new code locally on port 8090:
  - A valid refund returns `executed`.
  - A replay with the same `request_id` returns `already_executed` with the same `refund_id`.
  - An over-limit amount gets a 422 from the boundary. The SDK hang is bounded and fails with `RefundExecutionError` after about 6.6s (2 attempts × 3s + backoff).
  - The audit log shows `ALLOWED` and `DENIED_VALIDATION` rows.
  - The test refunds were deleted from the dev DB afterwards.

## Still pending
- ~~**Containers not rebuilt.**~~ Done after merging PR #39. See "Full-Stack Validation" below.
- **4xx errors are retried:** a 422 or 403 from the boundary is retried like any other failure, although it can never succeed. The retries are bounded, but they use up rate-limit quota. It could be classified as non-retryable later.
- **No dead-letter exchange:** a message NACKed after `EXECUTION_FAILED` is dropped. The transaction row keeps the status and the error for an operator.
- **Next steps:**
  - `validate_fraud_score` is still a stub, and there is no `orders` table yet. That is the next item (🟠 2: real read tools and evidence for the judges).
  - `test_transaction_repository.py` still runs `create_all` against the dev DB. It is what created the stray `refunds` table, so moving it to integration is now more urgent.
  - The dashboard's ingestion panel does not send `order_id`/`amount`/`currency` yet, so claims submitted from the UI end up `PENDING_HUMAN_REVIEW` (not executable) after approval.

---

# Update — Full-Stack Validation After Merge (2026-09-22)

PR #39 (`feat/real-refund-execution`) is merged into `main` (`39c857c`). This closes the last open item in its test plan.

## What was done
- Pulled `main`. The dev DB was already at head (`b3e1f0c9a2d4`), so the `migrate` service had nothing to apply.
- Rebuilt every image with `docker compose build` and started the stack with `docker compose up -d`. All 7 containers are up.
- Confirmed that `agentic_mcp_server` and `agentic_worker` run the new code.

## Real transaction through the full stack
Transaction `e2e-stack-1790128248`: order `ord-e2e-1`, 45.50 USD, submitted to the gateway at `POST /api/v1/claims`.
- **Judges:** Judge 1 (Gemini) and Judge 2 (GPT-OSS via Groq) both APPROVED with real calls. The Supreme Court was not needed.
- **Refund:** the worker called `execute_refund` through the MCP boundary. The trail records `execution: {"status": "executed", "refund_id": 1, ...}`, and the final status is `COMPLETED`.
- **Database:** there is one row in `refunds` (`ord-e2e-1`, 45.50, USD) and one `ALLOWED` audit row for `worker-default`.
- **Logs:** no errors or retries in the worker or MCP server logs.
- The test transaction and its refund are still in the dev DB.

## Found along the way (unrelated to the change)
- **Worker was down:** the worker had been exited for about 8 hours with `AMQPConnectionError: Name or service not known`, after RabbitMQ restarted. `docker compose up` brought it back.
- **LangSmith warnings:** the worker logs `403 Forbidden` warnings from LangSmith. Tracing is on, but the key is invalid. They don't affect processing.

---

# Next Steps (2026-09-22)

Step 1 (🔴 real execution) is done. Next in the list:

## 🟠 2. Real read tools and evidence for the judges
- **`orders` table with sample data, plus a `get_order` tool:** lets the system check that a refund doesn't exceed the purchase amount. CLAUDE.md §10 requires this check, and nothing performs it today.
- **`get_refund_history`:** the user's number of previous refunds.
- **`validate_fraud_score` with a real calculation:** it always returns `0.12` today. It would be computed from the refund history.
- **Evidence for the judges:** deterministic code fetches this data before judging and puts it in `<reference_context>`, the same way RAG works today. The judges stay one-shot, but they check against facts.

## Then, in this order
3. **Resolver (agent B):** an agent with read-only tools that proposes the action.
4. **Front-Desk (agent A):** chat with the user and delivery of the verdict.

## Smaller items that came up in step 1
- **Misplaced test:** `test_transaction_repository.py` runs `create_all` against the dev DB. It is what created the stray `refunds` table, so it moves up in priority.
- **Dashboard:** the claim form doesn't send `order_id`, `amount`, or `currency`, so claims submitted from the UI end up `PENDING_HUMAN_REVIEW`.
- **4xx errors:** they shouldn't be retried. They can never succeed, and each retry uses rate-limit quota.
- **Dropped messages:** a dead-letter queue is still missing for messages that end in `EXECUTION_FAILED`.
- **LangSmith:** fix the `403` warnings by disabling tracing or fixing the key.

## Recommendation
Start item 2 on a `feat/read-tools-and-evidence` branch. Include the small fixes that are closely related: moving the misplaced test and adding the fields to the dashboard form. Two decisions are needed from the user first:

1. **New `orders` table:** it needs a migration. Should it be created with sample data loaded by a script, like `ingest_knowledge_base.py`?
2. **New MCP tools:** `get_order` and `get_refund_history` would be new tools, and they need to be added to `worker-default`'s allowlist in `mcp_clients.json`. Should the worker get the evidence through the MCP server, passing through the boundary and landing in the audit log, instead of reading the database directly?
---

# Update — Branch `feat/read-tools-and-evidence`: Small Fixes and Design Decisions (2026-09-22)

Branch created from an up-to-date `main` (`39c857c`, pull confirmed nothing new). It carries this file's uncommitted "Next Steps" section from `chore/lastcontext-next-steps`, which had no commits of its own.

## Done on this branch

**Fix 4: misplaced test.** `tests/unit/test_transaction_repository.py` moved to `tests/integration/`. It was worse than noted: besides `create_all`, its teardown ran `TRUNCATE TABLE transactions ... CASCADE`, so every **unit** test run wiped the dev DB's transactions. The moved file:
- no longer calls `Base.metadata.create_all()` (the schema belongs to Alembic);
- deletes only its own `repo-test-%` rows, before and after, instead of truncating.
- Checked: the `e2e-stack-1790128248` transaction survives a run, and no `repo-test-%` rows are left.

**Fix 5: dashboard claim form.** The ingestion panel now has `Order ID`, `Refund Amount`, and `Currency` (from `src.core.currency.Currency`, the same enum as the gateway and the MCP schemas).
- `post_claim()` in `src/ui/api_client.py` sends them only when filled in. A blank field is omitted, not sent as `null` or `""` (the gateway rejects an empty `order_id` with a 422).
- A gateway 4xx (e.g. an amount above `REFUND_MAX_AMOUNT`) shows as `st.error` instead of crashing the page.
- Tests first: 2 new tests in `tests/unit/test_ui_api_client.py` (red, then green).
- Smoke-tested with Streamlit's `AppTest` against the live gateway: the fields render, and an over-limit amount shows the 422. A valid claim was not submitted, to avoid real LLM calls.

**Validation:** 117/117 unit tests pass (117 before − 2 moved to integration + 2 new). The 2 moved tests pass as integration tests. `ruff` and `mypy --strict` show only the two known pre-existing errors (BLE001 in `judge.py`, unused `type: ignore` in `llm_factory.py`). Dashboard container not rebuilt yet.

## Decisions taken for item 🟠 2 (delegated by the user: "do what you think best and note it")

**Decision 1: `orders` table, schema in a migration, sample data in a script.**
- A new Alembic migration creates `orders` (`order_id` unique, `user_id`, `amount` `Numeric(12,2)`, `currency`, `created_at`). Schema only, **no seed rows in the migration**: the same migrations will run against Cloud SQL (Phase 6), and fake orders must never land in a real database.
- Sample data comes from an idempotent script, `scripts/seed_orders.py` (`INSERT ... ON CONFLICT (order_id) DO NOTHING`), mirroring `scripts/ingest_knowledge_base.py`. It includes a few users with different refund histories, so the fraud score has something to differentiate.
- Per CLAUDE.md §8, `alembic current` and the target revision will be confirmed with the user before running the upgrade.

**Decision 2: the worker fetches the evidence through the MCP server, not the DB.**
- `get_order(order_id)` and `get_refund_history(user_id)` become MCP tools (read-only). `validate_fraud_score` stops being a stub and is computed from the refund history.
- They are added to `worker-default`'s allowlist in `mcp_clients.json`.
- Why:
  - Every data access that feeds a decision passes the Phase 1.B boundary and is written to the audit log, so the evidence the judges saw is traceable.
  - The same tools will be reused as-is by the Resolver (agent B), which will get its own `client_id` with a read-only allowlist. Building them in MCP now avoids a second implementation later.
  - It keeps the agent-facing layer free of DB access (CLAUDE.md §4).
- The cost is one extra HTTP/SSE round trip per tool. It uses the same fresh-session-per-attempt pattern as `refund_executor.py` (SDK 2.2.0 hang).
- **Evidence fetch fails closed on the business check:** if `get_order` fails or the order does not exist, the claim does not auto-approve (it goes to `PENDING_HUMAN_REVIEW`). This is unlike RAG, which fails open, because this is the check that stops a refund from exceeding the purchase (CLAUDE.md §10).
- The amount-vs-order check is done by **deterministic code**, not left only to the judges. The evidence is also injected into `<reference_context>` so the judges see it.

## New finding: the integration suite wipes the dev DB
Most integration fixtures `TRUNCATE` whole tables on the DB in `DATABASE_URL`, which is the dev DB: `transactions` (`test_database.py`, `test_transactions_router.py`, `test_worker.py`), `refunds` (`test_refund_repository.py`, `test_mcp_server.py`), `mcp_audit_logs` (`test_mcp_server.py`, `test_rate_limiter.py`), and **`knowledge_base`** (`test_knowledge_base_repository.py`). After a full integration run, the RAG table is empty until `ingest_knowledge_base.py` runs again. Recommended fix (separate `chore/` branch): a dedicated test database (`TEST_DATABASE_URL`, migrated with Alembic), and scoped deletes instead of truncates.

---

# Update — Branch `chore/isolated-test-database`: The Test Suite No Longer Touches the Dev DB (2026-09-22)

`feat/read-tools-and-evidence` was committed (`bcd7704`) without a PR, per the user. This branch starts from it, not from `main`, because the moved `tests/integration/test_transaction_repository.py` only exists there. Merge order: `feat/read-tools-and-evidence` first, then this one. Not pushed, no PR.

## What changed
- **`tests/support/database.py`:**
  - `resolve_test_database_url()` picks the test database: `TEST_DATABASE_URL`, or the dev database's name plus `_test` on the same server. It **fails closed**: a name that doesn't end in `_test`, or that matches the dev database, raises `UnsafeTestDatabaseError`.
  - `ensure_database_exists()` creates it through the `postgres` maintenance DB.
  - `migrate_to_head()` runs `alembic upgrade head` in-process. It is built without `alembic.ini`, so `fileConfig()` doesn't reconfigure logging mid-session.
- **`tests/conftest.py`:** at import time, before any test runs, points `settings.DATABASE_URL` and `os.environ["DATABASE_URL"]` (read by `alembic/env.py`) at the test database. On an unsafe URL it aborts the whole run with `pytest.exit`.
- **`tests/integration/conftest.py`:** a session-scoped autouse fixture creates and migrates the test database once.
- **Integration fixtures:** `Base.metadata.create_all()` removed from all 8. The schema now comes from the migrations, so a model change without its migration fails the suite instead of being hidden. `test_database.py` **hardcoded the dev DB's URL**, which would have bypassed any redirection; it now uses `settings.DATABASE_URL`. The `TRUNCATE`s stay: they are harmless on a throwaway database.
- **`src/core/config.py`:** new `TEST_DATABASE_URL` (default empty = derived). Documented in `.env.example`, README (Testing section, env table), and CLAUDE.md / GEMINI.md / AGENTS.md §9. `.env` itself was not touched.
- **CLAUDE.md §8 note:** the suite now runs `alembic upgrade head` automatically, but only against the guarded `_test` database, never against dev or cloud.

## Validation
- Tests first: 5 guard tests in `tests/unit/test_support_database.py` (red, then green).
- **159/159 pass** (122 unit + 37 integration), 82% line coverage over `src/` (down from 83% because of the new, UI-only lines in `src/ui/app.py`).
- **Dev DB untouched:** row counts were taken before and after a full run (`transactions` 1, `refunds` 1, `mcp_audit_logs` 2, `knowledge_base` 4) and are identical. Before this change, the same run emptied all four.
- **Guard checked:** `TEST_DATABASE_URL` pointed at `agentic_engine` aborts before any test runs.
- The test database `agentic_engine_test` now exists on the local server at head (`b3e1f0c9a2d4`).
- `ruff` and `mypy --strict` show only the two known pre-existing errors.

## Side effect found and fixed
The dev `knowledge_base` was **empty** (0 rows), most likely left that way by earlier integration runs. That means RAG context had been silently missing from the judges' prompts, because retrieval fails open. Re-ingested with `python -m scripts.ingest_knowledge_base` (4 chunks, real Gemini embeddings).

## Next
Back to 🟠 2 on `feat/read-tools-and-evidence` (rebased on this or after merge): the `orders` migration, `scripts/seed_orders.py`, and the `get_order` / `get_refund_history` MCP tools, following the decisions recorded above.

---

# Update — Branch `feat/orders-read-tools`: Part A of 🟠 2, Orders and Read Tools (2026-09-23)

🟠 2 was split into three increments, agreed with the user: **A** data and read tools (this branch), **B** evidence in the worker plus a deterministic amount check, **C** a real `validate_fraud_score` (it needs a formula and overlaps Phase 2, so it goes after B or into Phase 2).

This branch starts from `chore/isolated-test-database`. Merge order: `feat/read-tools-and-evidence` → `chore/isolated-test-database` → this one. Not pushed, no PR.

## What changed
- **`orders` table:** model `Order` and migration `c4d2a7e81f35` (`order_id` UNIQUE, `user_id` indexed, `amount` `Numeric(12,2)`, `currency`, `created_at`). Schema only.
- **`scripts/seed_orders.py`:** 6 sample orders for `user-1` (the dashboard's default), `user-2`, and `user-3`, in USD, EUR, and GBP, from 19.99 up to 2500. Idempotent (`ON CONFLICT DO NOTHING`, never overwrites).
- **Repositories:**
  - `order_repository.py`: `get_order()` and `insert_orders_if_absent()`.
  - `refund_repository.py`: `list_refunds_for_user()` (newest first, limited) and `summarize_refunds_for_user()` (count and per-currency totals, never summed across currencies).
  - `refunds` has no `user_id`: its `transaction_id` is the refunded `order_id`, so history is a **join through `orders`**. No change to `refunds` was needed. A refund whose order isn't in `orders` (like the old `ord-e2e-1`) doesn't appear in any user's history.
- **MCP tools**, both read-only:
  - `get_order(order_id)` returns `{status: found, order: {...}}` or `{status: not_found, order_id}`. Not found is data, not an error: part B decides what it means for the claim.
  - `get_refund_history(user_id, limit=20)` returns `refund_count` and `totals_by_currency` over **all** refunds, plus the `limit` most recent.
- **Boundary:** `GetOrderArgs` and `GetRefundHistoryArgs` in `TOOL_ARG_SCHEMAS` (non-empty ids, `1 <= limit <= 100`, `extra="forbid"`). A tool missing from that map would skip argument validation, and a test now guards it. Both tools are on `worker-default`'s allowlist in `mcp_clients.json`. `user_id` was already masked in the audit log.
- **Docs:** README (MCP Server section, tests, layout, known limitations), plus a new §5a step 11 in CLAUDE.md, GEMINI.md, and AGENTS.md.
- **Not done:** the add-mcp-tool runbook's "update the primary agent's prompt" step doesn't apply yet, since the primary agent is still mocked. It will apply to the Resolver.

## Validation
- Tests first (red, then green): schemas, the shipped allowlist, seed data, repositories (integration), and tools (direct call plus a 422 through HTTP with its `DENIED_VALIDATION` audit row).
- **183/183 pass** (135 unit + 48 integration), 83% coverage. The new migration also ran on the `_test` database through the suite, so it is exercised against real Postgres. `ruff` and `mypy --strict` show only the known pre-existing errors.
- **Dev DB:** confirmed with the user, then migrated `b3e1f0c9a2d4` → `c4d2a7e81f35` and seeded 6 orders. A second seed run inserted 0.
- **Containers:** rebuilt `mcp_server`, `migrate`, `worker`, and `sweeper`. `migrate` first failed with `Can't locate revision c4d2a7e81f35`, because the dev DB was already migrated but the image still had the old migrations. Rebuilding the worker-based images fixed it. **Lesson: after migrating dev from the host, rebuild every image built from `worker.Dockerfile` before `docker compose up`.**
- **Live through the real boundary** (token `worker-default`, `localhost:8080`):
  - `get_order("ord-1001")` returned `found` (45.50 USD, user-1).
  - `get_order("ord-nope")` returned `not_found`.
  - `get_refund_history("user-1")` returned 0 refunds.
  - Three `ALLOWED` audit rows, with `user_id` masked. They remain in the dev DB.

## Next: part B
The worker fetches `get_order` and `get_refund_history` through MCP before the judges, generalizing the fresh-session-per-attempt pattern from `refund_executor.py` to any tool. It then:
- checks deterministically that the amount doesn't exceed the order, the currency matches, and the order belongs to the claim's `user_id`;
- fails closed to `PENDING_HUMAN_REVIEW` if a check fails, or if the order can't be read or doesn't exist;
- injects the evidence into `<reference_context>` and records it in `judge_trail["evidence"]`.

---

# Pending Work and Plan (2026-09-23)

## Still pending from 🟠 2

**B. Evidence in the worker (next).** Touches the `worker.py` flow, but not ACK/NACK.
- Before the judges, the worker fetches `get_order(order_id)` and `get_refund_history(user_id)` through MCP. Generalize `refund_executor.py`'s pattern (a fresh session per attempt, `read_timeout_seconds`, exponential backoff) into a reusable caller for any tool.
- A deterministic check, in code and not left to the judges:
  - the requested `amount` does not exceed the order's `amount`;
  - the `currency` matches the order's;
  - the order belongs to the claim's `user_id`.
- **Fails closed:** if a check fails, the order doesn't exist, or it can't be read after the retries, the claim does not auto-approve and goes to `PENDING_HUMAN_REVIEW`, with the reason in the trail. This is unlike RAG, which fails open, because this is the CLAUDE.md §10 check.
- The evidence is injected into `<reference_context>`, so the judges verify against facts, and recorded in `judge_trail["evidence"]`.
- A claim without `order_id` keeps its current behavior (nothing to verify or execute, so `PENDING_HUMAN_REVIEW`).
- Dashboard: show the evidence in the decision inspector.
- Tests first: unit tests for the check (under, equal, over the amount; wrong currency; another user's order; not_found; tool failure), plus integration through the worker.

**C. Real `validate_fraud_score` (after B, or in Phase 2).** It returns a fixed `0.12` today. It needs:
- a formula (e.g. from `refund_count` and `totals_by_currency` in `get_refund_history`);
- changing its arguments, which is a tool contract change (§8, confirm with the user).

It overlaps the Phase 2 rule base, so it may make more sense to build it there.

## Stronger load data and test coverage (for the job application)

**What today's Locust numbers measure:** they hit `POST /api/v1/claims`, which answers 202 once the claim is published to RabbitMQ. The P95 of 87 ms is **ingestion**, not processing: it excludes the judges, RAG, and the refund. Raising users against the same endpoint mostly measures the laptop (Locust tends to saturate before FastAPI). The number gets bigger, not more solid.

**Plan, in order of value:**
1. **CI in GitHub Actions with a coverage gate.** README and CLAUDE.md say CI runs on every PR, but **there is no `.github/workflows`**, and a technical reviewer will notice. The workflow:
   - runs ruff, mypy `--strict`, and pytest, with Postgres (`pgvector/pgvector:pg16`) and RabbitMQ as services;
   - fails if coverage drops below 80% (`--cov-fail-under=80`).

   It maps directly to the job posting ("CI/CD, GitHub Actions", "clear coverage thresholds"). The two pre-existing lint/type errors (BLE001 in `judge.py`, unused `type: ignore` in `llm_factory.py`) must be fixed first, or CI starts red.
2. **Correctness under load and chaos (the most valuable result).**
   - Send N claims (e.g. 2,000), about 10% of them deliberate duplicates (same `request_id`).
   - During the run, kill the worker twice and restart RabbitMQ once.
   - At the end, verify in the DB: 0 duplicate refunds, 0 lost messages (every `request_id` in a final state), and the Recovery Sweeper reclaiming what was left in `PROCESSING`.
   - Target sentence: "2,000 claims, 10% duplicates, worker killed mid-run twice → 0 double refunds, 0 lost messages."
   - **Prerequisite:** run it with mock providers, so there's no LLM cost and no rate limits. Judge 2, the Supreme Court, and the Prompt Guard hardcode their provider and ignore `LLM_PROVIDER=mock`. This needs a test-only override, or part of Phase 1.F first.
3. **End-to-end processing throughput:** with mocks, claims/second with 1, 2, and 4 workers, plus end-to-end latency (`created_at` → `updated_at`). It shows horizontal scaling.
4. **Stepped ingestion load:** 100 → 250 → 500 → 1000 users until the breaking point. Report the max RPS with P95 under a threshold, plus the hardware. Use distributed Locust (`--processes`), so Locust isn't the bottleneck. This is the least differentiating of the four.

**Coverage:** 83% is supporting data, not the headline. What's tested matters more: idempotency against real Postgres, the boundary's 401/403/422/429 responses with their audit rows, and retries with timeouts. On the CV: "183 tests, integration tests against real Postgres/RabbitMQ, 83% coverage." As a CI gate, it becomes directly relevant.

**Suggested order:** CI with a coverage gate → the chaos/idempotency test with mocks → throughput and stepped ingestion if there's time. Then B.

## Branches (merge in this order)
`feat/read-tools-and-evidence` (`bcd7704`) → `chore/isolated-test-database` (`001e4e3`) → `feat/orders-read-tools` (`602e54f`, plus this note). Each branch contains the one before it, so pushing `feat/orders-read-tools` carries all the commits.

---

# Update — Branch `chore/ci-github-actions`: CI with a Coverage Gate (2026-09-23)

Branch starts from `feat/orders-read-tools`, so it carries all three earlier branches.

## What changed
- **`.github/workflows/ci.yml`:** runs on every push, and can also be triggered by hand. A PR shows the checks of its head commit.
  - Job **Lint and types:** `ruff check src tests` and `mypy src`.
  - Job **Tests and coverage:** `pytest tests --cov=src --cov-fail-under=80`, against `pgvector/pgvector:pg16` and `rabbitmq:3` service containers. `DATABASE_URL` points at the service, and `tests/conftest.py` redirects to `agentic_engine_test` and migrates it. `LLM_PROVIDER=mock`, and no API keys or secrets are used.
  - Python 3.11, the same version as the Dockerfiles, with a pip cache.
- **The two pre-existing errors are fixed, so CI starts green:**
  - BLE001 in `judge.py`: the Supreme Court catch-all is deliberate (any failure ends in REJECT). It now carries `# noqa: BLE001 -- <reason>`, the convention the rest of the code already uses.
  - Unused `type: ignore` in `llm_factory.py`: this error **depended on the environment**. `langchain-google-vertexai` and `langchain-openai` are installed in the local venv but are not declared dependencies, so in CI the same `ignore` would have been necessary, and `langchain_openai` would have failed with `import-not-found`. Fixed in `pyproject.toml`: `[[tool.mypy.overrides]]` with `ignore_missing_imports` for those three optional modules, and plain imports.
- **`pyproject.toml`:** pins `ruff==0.16.8` and `mypy==2.3.1` in `dev`. The repo had no ruff config, so it used ruff's defaults, which in 0.16 are **413 rules** and change between releases. Without the pin, CI would have linted with a different version than local. Also adds `[tool.mypy] strict = true`.
- **README:** a real CI status badge replaces the static "124 passing" / "81%" badges, which were outdated. Coverage badge updated to 83%. The "no CI/CD pipeline" line is corrected, and a CI bullet is added in Testing.

## Validation
It was simulated before pushing, in a clean copy of the repo: no `.env`, a fresh venv, `pip install -e ".[dev]"`, and none of the optional providers. `ruff` passed, `mypy` passed, and **183 passed with 83.63% coverage** (gate 80%). The only difference from CI is Python 3.12 locally versus 3.11 in CI. The first real run on GitHub confirms it.

## Suggested next step (manual, in GitHub)
Settings → Branches → a protection rule on `main` requiring the "Lint and types" and "Tests and coverage" checks. That way a red PR can't be merged. It needs the GitHub UI, since there is no `gh` CLI.
