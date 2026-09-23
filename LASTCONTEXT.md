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
