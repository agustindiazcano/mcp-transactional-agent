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
- **Containers not rebuilt:** `agentic_mcp_server` still runs the old code. The next step is `docker compose build` plus one real transaction through the full stack, with a claim that carries `order_id` and `amount`.
- **4xx errors are retried:** a 422 or 403 from the boundary is retried like any other failure, although it can never succeed. The retries are bounded, but they use up rate-limit quota. It could be classified as non-retryable later.
- **No dead-letter exchange:** a message NACKed after `EXECUTION_FAILED` is dropped. The transaction row keeps the status and the error for an operator.
- **Next steps:**
  - `validate_fraud_score` is still a stub, and there is no `orders` table yet. That is the next item (🟠 2: real read tools and evidence for the judges).
  - `test_transaction_repository.py` still runs `create_all` against the dev DB. It is what created the stray `refunds` table, so moving it to integration is now more urgent.
  - The dashboard's ingestion panel does not send `order_id`/`amount`/`currency` yet, so claims submitted from the UI end up `PENDING_HUMAN_REVIEW` (not executable) after approval.