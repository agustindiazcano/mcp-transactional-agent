# 📝 Roadmap: Agentic MCP Engine

Personal working notes: only what is still open, in priority order. Everything done up to 2026-09-25 morning (Part B merged as PR #69, the session-start-hook as PR #70): [docs/worklog/2026-09-25-pending-snapshot.md](docs/worklog/2026-09-25-pending-snapshot.md). Older: [docs/worklog/2026-09-24-pending-snapshot.md](docs/worklog/2026-09-24-pending-snapshot.md). README.md holds the canonical, detailed version.

## Priority Order

### 0 — 🔴 Audit findings (2026-10-14): verified against the code, README already corrected
An external review of the README was checked claim by claim. The doc inconsistencies are fixed in README.md; these are the code and process items that remain. Verified TRUE unless noted.
- [ ] 🔴 **`execute_refund` enforces no business invariant** (`src/mcp_server/mcp_server.py`, `refund_repository.record_refund`). Idempotency is by `request_id` only; the "refund + history <= order" cap lives in the worker's evidence check as check-then-act (TOCTOU between concurrent workers, and two `request_id`s on one order refund twice). Move the check inside the tool, in one transaction with a row lock on the order (`SELECT ... FOR UPDATE` on `orders`), test-first with a concurrency test. Touches the MCP tool contract: confirm with the user first (CLAUDE.md §8).
- [ ] 🔴 **Decide the cascade rule.** `evaluate_decision()` lets the Supreme Court APPROVE over two REJECTs (`judge.py`). Benchmark: Judge 2 had 0 false approvals, Judge 1 had 3 cases; "any reject goes to a human" gave 0. Phase 1.G forbids approving over a rejection, the live pipeline does it. Options: keep, require unanimity, or let the Supreme Court only confirm/route. User decision; changing it needs the eval re-run.
- [x] 🟡 **Dead setting `IDEMPOTENCY_TTL_SECONDS`** removed from `config.py`, `.env.example`, README and CLAUDE.md (2026-10-14). Left in the user's own `.env` (harmless: settings ignore extras; CLAUDE.md §8 needs approval to edit it).
- [ ] 🟡 **Fail-open on security inputs** (Prompt Guard, retrieval) and Groq as both Judge 2 and the Prompt Guard. Decide per input: fail closed to `PENDING_HUMAN_REVIEW`, or accept and keep documenting. Consider a second guard provider.
- [ ] 🟡 **Audit row never records the outcome** (`"invoked"` only). Needs a second correlated row or a result-update path; weigh against the insert-only design.
- [ ] 🟡 **Throughput headline vs. the default rate limit:** the 9–19.6 claims/s figures used the limit lifted; default `MCP_RATE_LIMIT_PER_MIN=30` on the shared `worker-default` client caps `execute_refund` near 0.5/s. Decide: per-worker clients, a higher default, or document only (README status table now says so).
- [ ] 🟡 **Re-run Locust** against the stack now (the 87 ms numbers predate the persistent-message fix). Publisher confirms are NOT a gap: aio-pika 10 publishes with confirms by default and the chaos test lost nothing.
- [ ] 🟡 **Benchmark statistics:** repeats are not independent (effective n = 34 non-approvable / 16 approvable). Add more cases (toward ~100), real-retrieval context instead of the oracle chunk, runs spread over time, then report intervals. Re-run after Part B.
- [ ] 🟡 **Explain the latency gap:** benchmark median 9.3 s (Judge 1) / 4.0 s (Judge 2) vs. 4.6-6.6 s for a whole claim. Hypothesis: eval concurrency. Measure with concurrency 1.
- [ ] 🟡 **Re-measure cost per transaction** (stale: prompts ~600 tokens, not 320; the Supreme Court is 5.5x costlier; Front-Desk call missing; no Vertex cost row).
- [ ] 🟡 **Claim text goes unmasked to Gemini/Groq.** Decide whether to mask PII before the LLM calls or to document it as accepted (it is now in README Known Limitations).
- [ ] 🟢 **Phases 2, 3, 5 have nothing falsifiable.** `rule_base.py`, `fuzzy_layer.py`, `kalman_monitor.py`, `alerting.py` are empty files (README previously said Phase 3 had built parts: FALSE, they are 0 bytes). Before building: give each an acceptance criterion; Phase 3 needs a numeric score series (judges emit binary verdicts); Phase 2's tier/freshness are constant with one document; Phase 5 needs labels (fraud score is fixed at 0.12).
- [ ] 🟢 **Cloud Run traces** (Langfuse keys into Secret Manager) so the README's tracing claim holds in the cloud.
- [ ] 🟢 **README is too long for a first read** (~1,100 lines): move the Phase 1.B-1.G detail into `docs/` and keep status and results. Use one source for counts (done for tests: Testing section) and a dynamic coverage badge (the 86% badge is static).
- [ ] 🟢 **Housekeeping:** the comments in `worker.py` (~lines 104, 136) still say the primary agent is "still mocked"; CLAUDE.md §5a step 4 and §2 were stale (fixed 2026-10-14). Dashboard exposes transactions and judge reasoning publicly (see §4 login item).
- Checked and NOT a problem / already correct: evidence check exists (README sections that said otherwise are fixed); the DLQ row in the contract claimed a dead-letter queue that doesn't exist (fixed to match Known Limitations).

### 1 — 🔴 Front-Desk / Back-Office Asymmetric Agentic Workflow (Phase 1.E) — promoted 2026-09-25
Part B (below) is merged, so this is unblocked. Replaces `worker.py`'s hardcoded `mock_primary_action = "execute_refund"` with a real primary-agent LLM call, and extends "never trust LLM output, validate server-side" to the agent's proposed intent. Decided 2026-09-25: **single-turn first** (claim text → validated proposal → judges); the multi-turn chat variant is a later increment on top of it, not this pass.
- [x] Proposal schema (Pydantic, `extra="forbid"`): intent (refund / clarify / out_of_scope), order_id, amount, currency, reason. `src/agents/proposal.py`'s `ClaimProposal`, branch `claude/awesome-wright-bipend`, 2026-09-25.
- [x] Front-Desk: a real LLM call in `src/agents/` (structured output through `llm_factory`), minimal privilege (no DB/RAG table/MCP access), that translates free text into that schema — or asks a clarifying question if it can't. `src/agents/front_desk.py`'s `propose_action()`, same branch. Fails closed to `clarify` on any malformed reply or provider failure.
- [x] Back-Office: wire `propose_action()` into `worker.py` in place of the mock, intent gate only (user decision, 2026-09-25): a non-refund intent (clarify/out_of_scope) routes to `PENDING_HUMAN_REVIEW` with no evidence check or judge call; a refund intent proceeds through evidence and the judges exactly as before, using the claim's own structured `order_id`/`amount`/`currency`, not the proposal's. Recorded as `judge_trail["front_desk"]`. Branch `claude/awesome-wright-bipend`, same date.
- [x] Self-correction loop, narrow scope (user decision, 2026-09-25): on a judge REJECT, `worker.py` gives the Front-Desk one reclassification attempt (`propose_action(claim_text, rejection_feedback=<judge's reason>)`). A reclassification away from `refund` becomes the human-review reason (`judge_trail["front_desk_retry"]`); an unchanged `refund` means the judges are never called twice. Deliberately doesn't let a REJECT revise `order_id`/`amount`/`currency` — those still come from the claim's structured fields, not the proposal (would need the declined "full replacement" design). Branch `claude/awesome-wright-bipend`, same date.
- [x] `NEEDS_CLARIFICATION` outcome: a new status with the agent's question, shown on the dashboard. `worker.py` routes a `clarify` intent (initial proposal or the retry reclassification) to `NEEDS_CLARIFICATION` instead of `PENDING_HUMAN_REVIEW`; `out_of_scope` still routes to `PENDING_HUMAN_REVIEW` (nothing to ask). Dashboard: `src/ui/trail.py`'s `describe_clarification_question()` surfaces the question in the decision-inspector expander, and `NEEDS_CLARIFICATION` is in `theme.py`'s `ALERT_STATUSES`. Branch `claude/awesome-wright-bipend`, 2026-09-25.
- [ ] Feedback loop: the objective verdict contract (`REJECTED: <objective reason>`, never raw judge rationale) that the Front-Desk phrases into a reply, without re-interpreting or overriding it.
- [x] Promptfoo eval for the proposer built (commit `dc79858`, branch `feat/front-desk-eval`, `evals/promptfoo/`). Still open: confirm the user reviewed the labels, and run it against real models.
- [ ] A real run on Vertex, docs, PR. Real cost here is Gemini/Groq/Vertex API usage, a separate budget from the $100 Anthropic cloud credits (those cover Claude Code cloud sessions, not LLM provider calls).
- [ ] Chat abuse limits (only once the chat variant is built): per-user message rate and daily token budget ([analysis](docs/architecture/api_abuse_protection.md), section 4).
- [ ] Re-measure cost per transaction once the primary agent is real, averaged over more transactions (today: one happy-path measurement, ~$0.0004).

### 2 — 🟢 Evidence for the judges (Part B) cleanup — core merged as PR #69
- [x] The worker fetches `get_order` / `get_refund_history` through MCP before judging.
- [x] A deterministic check (amount ≤ order, same currency, order owned by the claim's user, currency-aware limit) fails closed to `PENDING_HUMAN_REVIEW`.
- [x] Evidence injected into `<reference_context>` and recorded in `judge_trail["evidence"]`. Closes the CLAUDE.md §10 "refund exceeds the original amount" check.
- [x] The worker holds a DB transaction open from retrieval through the judges and the refund call ("idle in transaction" for seconds with real LLMs). Commit or close it after retrieval.
- [ ] Check the cloud `worker-cloud` allowlist (`mcp-clients-json` secret) includes `get_order` and `get_refund_history` before the next cloud demo.
- [ ] Re-run the chaos test against the stack (it now seeds an order per claim).
- [ ] Dev DB: `ord-1001` has $182 refunded on a $45.50 order and `ord-1002` is fully refunded, from runs before the check; re-seed or pick other orders for demos.
- [ ] Re-run the eval: `b2-reject-04` ($3,000 refund on a "$30 charger") must become impossible to approve now that Part B is live.

### 3 — 🟡 LLMOps follow-ups (Promptfoo, Langfuse, RAG)
- [ ] **RAG chunker splits a heading from its rules — code fixed 2026-10-14 (a heading now moves to the next chunk, test-first); still open: re-run `ingest-knowledge-base` locally and in Cloud SQL, then re-run the eval.** Original finding: (found 2026-09-24 by the Promptfoo harness). `chunk_markdown()` packs paragraphs greedily, so `## Refund Amount Limits and Fraud Flags` ends chunk 1 while its rules ($5000 review, fraud flag) start chunk 2; `## Refund Method` and `## Non-Refundable Items` the same. A claim can retrieve the heading-only chunk and the judges get no rule, silently. The docstring promises the opposite. Fix test-first (a heading must never end a chunk), then re-run `ingest-knowledge-base` locally and in Cloud SQL.
- [ ] **Verdicts drift between runs:** measure with repeats spread over time (the euro case itself needs Part B).
- [ ] Evaluate the full cascade (both judges + Supreme Court) as its own Promptfoo provider, to measure that instead of inferring it.
- [ ] CI gate: run the eval when the judge prompt, parser or models change (or on demand), fail on any false approval. Needs Vertex auth in CI (a separate eval service account through Workload Identity Federation) and `GROQ_API_KEY` as a GitHub secret.
- [ ] GPT-OSS returned an empty reply 2 of 3 times on the Spanish claim (`b2-approve-04`); the parser failed closed to REJECT. Check whether it answered only in its reasoning channel.
- [ ] Promptfoo red-team probes for prompt injection (the 9 hand-written attacks were all blocked by all models).
- [ ] More cases toward ~100, from real claims once Phase 1.E produces varied intents.
- [ ] Langfuse: custom model prices for `openai/gpt-oss-20b`, `llama-prompt-guard-2-22m`, `gemini-embedding-001` (cost shows empty today).
- [ ] Langfuse on Cloud Run: keys into Secret Manager (`langfuse-public-key`, `langfuse-secret-key`), mounted on the worker pool, `LANGFUSE_TRACING_ENVIRONMENT=demo`.
- [ ] Langfuse: judge verdicts as scores (per-judge APPROVE/REJECT, judge agreement), feeding the judge-calibration work.
- [ ] **Turn LangSmith off.** Unset `LANGCHAIN_TRACING_V2` in `.env`: tracing is on with an invalid key, which is where the worker's `403` warnings come from.
- [ ] **Gemini ignores `temperature=0.0`** (`langchain-google-genai` warns the model "uses fixed sampling defaults"), so Judge 1 and the Supreme Court don't run at temperature 0, although the docs say both judges do. Groq's Judge 2 honors it. Correct the docs or pick a Gemini model that accepts sampling parameters.
- [ ] **Ragas (RAG evaluation), later:** context relevance and groundedness of the retrieval → judge path, once the knowledge base has more than its current 4 chunks.

### 4 — 🟡 Google Cloud leftovers (Phase 6)
- [ ] Test the first real `demo-up` (down → up cycle): Cloud SQL, the pools, one claim.
- [ ] Re-run the Locust load test against Cloud Run and compare with the local baseline (P95 87 ms, 0 failures).
- [ ] **Public API abuse protection — decision pending** ([analysis](docs/architecture/api_abuse_protection.md)). No limit per IP or per user on `POST /api/v1/claims`; one claim can trigger up to 11 LLM calls. Options: `slowapi` per-IP limit in the gateway (free, ~1–2 h), per-user limit in Postgres (after a login), Cloud Armor (~$18+/month), or `demo-down` when not demoing. Small fix in any case (the `claim_text` `max_length` is done, 2026-10-14): `request_id` is optional, so a client retry without one isn't deduplicated.
- [ ] Login for the dashboard and gateway (public today; anyone can send claims that cost LLM calls).
- [ ] Add `deletion_policy = "ABANDON"` to `google_sql_user.app` before any teardown (`app` owns the tables, so dropping the user fails).
- [ ] Mojibake in Judge 2's reasons (`userâ€™s` for `user’s`), stored that way in `judge_trail`. Find where the Groq text is mis-decoded; test first.
- [x] (code done 2026-10-14, takes effect on the next cloud deploy) `/api/v1/system-health` reports the MCP server down on the first call after idle (3 s timeout < cold start). Raise the timeout, or accept it for the demo.
- [ ] Add `bandit` / Ruff's `S` rules to CI (security lint).
- [ ] **SQLAlchemy 2.1:** capped at `<2.1` since 2.1.0 broke fresh builds (no `greenlet` by default). Upgrade on its own branch, run the full suite, then lift the cap.
- [ ] Automatic rotation of the cloud secrets (today a new version is added by hand).
- [ ] Later, only with a paid billing account: Claude (`claude-haiku-4-5`, `claude-sonnet-5`) and Grok 4.20 on Vertex, e.g. a third-family Supreme Court.

### 5 — 🟢 Reliability backlog
- [ ] MCP server replicas: its single process caps near 34 claims/s (~29 ms CPU per claim). The audit-table rate limiter already works across replicas.
- [ ] **Stepped ingestion load:** Locust 100 → 250 → 500 → 1000 users with `--processes`; max RPS with P95 under a threshold, plus the hardware.
- [x] Don't retry 4xx responses from the MCP boundary (`is_permanent_rejection()` in `src/worker/mcp_client.py`, 2026-10-14; 408/429 still retry). Open: confirm against the live stack that a rejected POST surfaces as an `HTTPStatusError` and not only as a read timeout.
- [ ] Dead-letter queue for `EXECUTION_FAILED` messages (today they are dropped; the row keeps the error).
- [ ] A redelivered message whose row is still `PROCESSING` waits for the sweeper's stale threshold (5 min) — delayed, not lost.
- [ ] **Real `validate_fraud_score` (Part C):** a formula over the refund history; changes the tool's arguments (contract change, confirm first). May belong in Phase 2.
- [ ] MCP audit table: a DB role actually restricted to `INSERT`/`SELECT` (insert-only is a code convention today).
- [ ] Dashboard: RAG detail view (which policy chunk was injected); the expander shows only the judge trail and payload.

### 6 — ⚪ Dynamic LLM Provider Selection (Phase 1.F)
- [ ] Per-request override: optional `judge_1_provider`/`judge_2_provider` fields on `ClaimRequest`, validated against `get_llm()`'s provider allowlist; two `st.selectbox` dropdowns in the dashboard's ingestion panel; `evaluate_decision()` accepts explicit providers, falling back to `provider_for_role()` when unset.
- [ ] Global hot-swappable default: an admin surface (e.g. `PUT /config/providers`) backed by `pydantic-settings` and/or a config table — a "vendor is down, reroute now" lever with no restart. Later increment.

### 7 — ⚪ High-Value Court (Phase 1.G) — planned
Design: [docs/architecture/high_value_court.md](docs/architecture/high_value_court.md).
- [x] Prerequisite met: Part B (deterministic evidence checks + currency conversion to USD) merged as PR #69.
- [ ] Routing by amount in USD: < $1,000 today's pipeline; $1,000–$5,000 the court; > $5,000 human review (policy). `HIGH_VALUE_THRESHOLD_USD`, default 1000.
- [ ] Four judges from four different model families, all must APPROVE (families to confirm on Groq and measure with the eval).
- [ ] Superior judge (candidate: Gemini Pro, check the trial credit covers it): on any rejection it can only confirm the REJECT or route to human review. **Never approves over a rejection** (user decision).
- [ ] Pick the models with the Promptfoo eval; grade the whole court as one provider on new $1,000–$5,000 cases, repeats spread over time. Acceptance bar: zero false approvals.

### 8 — ⚪ Internal Review Panel + Resolver Agents (Phase 1.H) — idea noted 2026-10-14, not designed
An internal-user panel to work the rejected / `PENDING_HUMAN_REVIEW` / `NEEDS_CLARIFICATION` claims. Agents analyze each one with RAG and tools and classify it; a smarter agent sits above them. This is the "resolver agent (agent B)" from LASTCONTEXT's decisions list, which needs the user's go-ahead before it changes the Phase 1.E design: this note is the request, not the approval.
- [ ] Design doc first (`docs/architecture/`): scope, who the internal user is, what the panel can do (read-only triage vs. approve/reject), and how it relates to Phase 1.E, 1.G and the dashboard.
- [ ] Review queue: the panel lists claims in the review statuses, with the full `judge_trail` (Front-Desk, evidence, judges, Supreme Court) next to each.
- [ ] Analyst agents: per claim, retrieve policy with RAG and call **read-only** MCP tools (`get_order`, `get_refund_history`), then **classify** the case (e.g. likely legitimate, likely fraud, needs documents, policy gap) with a short evidence-backed reason.
- [ ] Smarter agent (stronger model, e.g. Gemini Pro; check the trial credit covers it) that reviews the analysts' classifications and resolves disagreements between them.
- [ ] Authority boundary (to decide with the user): agents only recommend; any approval or refund still goes through the human and `refund_executor.py`. Per CLAUDE.md §4, no LLM calls a write tool.
- [ ] Security: the panel reads through the gateway API like the dashboard (no direct DB); its MCP client gets its own `client_id` with a read-only allowlist (Phase 1.B). Login required, since it exposes claim data.
- [ ] Trace in Langfuse (new observation names) and add a Promptfoo eval for the classification.
- [ ] Open questions: new Streamlit page or separate service? Does the human's decision feed back as labels for the evals (judge calibration)?

### 9 — ⚪ Deterministic Confidence Layer (Phase 2)
- [ ] Integrate the fuzzy-scoring layer and the Belief Rule Base alongside the AI Judge, so critical transactions (`execute_refund`, `validate_fraud_score`) require double approval — probabilistic (LLM judge) *and* symbolic (rule base) — before auto-approving.

### 10 — ⚪ Quality Drift Detection (Phase 3)
- [ ] Implement the async monitor with a statistical filter (EWMA default, CUSUM/Page-Hinkley/Kalman as options) to detect whether model responses are degrading over time. Runs off the critical path — never blocks transaction processing.

### 11 — ⚪ AWS (Phase 6, secondary target)
- [ ] Configure IAM credentials and AWS Bedrock access (least privilege, VPC PrivateLink).
- [ ] Swap the embeddings module to Amazon Titan behind `get_embeddings()`.
- [ ] Serverless topology: AWS API Gateway + SQS + Lambda + serverless PostgreSQL (Neon with pgvector).
