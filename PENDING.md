# 📝 Roadmap: Agentic MCP Engine

Personal working notes: only what is still open, in priority order. Everything done up to 2026-09-24 (Steps 1, 2 and 4, the Promptfoo and Langfuse work, GCP steps 1–10, reliability and security passes): [docs/worklog/2026-09-24-pending-snapshot.md](docs/worklog/2026-09-24-pending-snapshot.md). README.md holds the canonical, detailed version.

## Priority Order

### 1 — 🔴 Evidence for the judges (Part B) — next
Real example 2026-09-23: Judge 2 rejected a valid $45.50 claim because it couldn't verify the 30-day window without the purchase date. The benchmark shows Judge 1 approving a $3,000 refund on a "$30 charger", and both judges approving a €4,800 claim (over the $5,000 limit) 4 of 5 times.
- [ ] The worker fetches `get_order` / `get_refund_history` through MCP before judging.
- [ ] A deterministic check (amount ≤ order, same currency, order owned by the claim's user, currency-aware limit) fails closed to `PENDING_HUMAN_REVIEW`.
- [ ] Evidence injected into `<reference_context>` and recorded in `judge_trail["evidence"]`. Closes the CLAUDE.md §10 "refund exceeds the original amount" check.
- [ ] The worker holds a DB transaction open from retrieval through the judges and the refund call ("idle in transaction" for seconds with real LLMs). Commit or close it after retrieval.
- [ ] After Part B, re-run the eval: `b2-reject-04` ($3,000 refund on a "$30 charger") must become impossible to approve.

### 2 — 🟡 LLMOps follow-ups (Promptfoo, Langfuse, RAG)
- [ ] **RAG chunker splits a heading from its rules** (found 2026-09-24 by the Promptfoo harness). `chunk_markdown()` packs paragraphs greedily, so `## Refund Amount Limits and Fraud Flags` ends chunk 1 while its rules ($5000 review, fraud flag) start chunk 2; `## Refund Method` and `## Non-Refundable Items` the same. A claim can retrieve the heading-only chunk and the judges get no rule, silently. The docstring promises the opposite. Fix test-first (a heading must never end a chunk), then re-run `ingest-knowledge-base` locally and in Cloud SQL.
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

### 3 — 🟡 Google Cloud leftovers (Phase 6)
- [ ] Test the first real `demo-up` (down → up cycle): Cloud SQL, the pools, one claim.
- [ ] Re-run the Locust load test against Cloud Run and compare with the local baseline (P95 87 ms, 0 failures).
- [ ] **Public API abuse protection — decision pending** ([analysis](docs/architecture/api_abuse_protection.md)). No limit per IP or per user on `POST /api/v1/claims`; one claim can trigger up to 11 LLM calls. Options: `slowapi` per-IP limit in the gateway (free, ~1–2 h), per-user limit in Postgres (after a login), Cloud Armor (~$18+/month), or `demo-down` when not demoing. Small fixes in any case: `max_length` on `claim_text`; `request_id` is optional, so a client retry without one isn't deduplicated.
- [ ] Login for the dashboard and gateway (public today; anyone can send claims that cost LLM calls).
- [ ] Add `deletion_policy = "ABANDON"` to `google_sql_user.app` before any teardown (`app` owns the tables, so dropping the user fails).
- [ ] Mojibake in Judge 2's reasons (`userâ€™s` for `user’s`), stored that way in `judge_trail`. Find where the Groq text is mis-decoded; test first.
- [ ] `/api/v1/system-health` reports the MCP server down on the first call after idle (3 s timeout < cold start). Raise the timeout, or accept it for the demo.
- [ ] Add `bandit` / Ruff's `S` rules to CI (security lint).
- [ ] **SQLAlchemy 2.1:** capped at `<2.1` since 2.1.0 broke fresh builds (no `greenlet` by default). Upgrade on its own branch, run the full suite, then lift the cap.
- [ ] Automatic rotation of the cloud secrets (today a new version is added by hand).
- [ ] Later, only with a paid billing account: Claude (`claude-haiku-4-5`, `claude-sonnet-5`) and Grok 4.20 on Vertex, e.g. a third-family Supreme Court.

### 4 — 🟢 Reliability backlog
- [ ] MCP server replicas: its single process caps near 34 claims/s (~29 ms CPU per claim). The audit-table rate limiter already works across replicas.
- [ ] **Stepped ingestion load:** Locust 100 → 250 → 500 → 1000 users with `--processes`; max RPS with P95 under a threshold, plus the hardware.
- [ ] Don't retry 4xx responses from the MCP boundary (they can't succeed and use rate-limit quota).
- [ ] Dead-letter queue for `EXECUTION_FAILED` messages (today they are dropped; the row keeps the error).
- [ ] A redelivered message whose row is still `PROCESSING` waits for the sweeper's stale threshold (5 min) — delayed, not lost.
- [ ] **Real `validate_fraud_score` (Part C):** a formula over the refund history; changes the tool's arguments (contract change, confirm first). May belong in Phase 2.
- [ ] MCP audit table: a DB role actually restricted to `INSERT`/`SELECT` (insert-only is a code convention today).
- [ ] Dashboard: RAG detail view (which policy chunk was injected); the expander shows only the judge trail and payload.

### 5 — ⚪ Front-Desk / Back-Office Asymmetric Agentic Workflow (Phase 1.E)
Replaces `worker.py`'s hardcoded `mock_primary_action = "execute_refund"` with a real primary-agent LLM call, and extends "never trust LLM output, validate server-side" to the agent's proposed intent.
- [ ] Front-Desk: a conversational LLM, minimal privilege (no DB/RAG table/MCP access), that translates free text into a structured JSON payload proposing intent — or asks a clarifying question if it can't.
- [ ] Back-Office: re-validate that payload server-side against a strict Pydantic schema (`extra="forbid"`) before it reaches the Double Judge.
- [ ] Feedback loop: the objective verdict contract (`REJECTED: <objective reason>`, never raw judge rationale) that the Front-Desk phrases into a reply, without re-interpreting or overriding it.
- [ ] Chat abuse limits: per-user message rate and daily token budget ([analysis](docs/architecture/api_abuse_protection.md), section 4).
- [ ] Re-measure cost per transaction once the primary agent is real, averaged over more transactions (today: one happy-path measurement, ~$0.0004).

### 6 — ⚪ Dynamic LLM Provider Selection (Phase 1.F)
- [ ] Per-request override: optional `judge_1_provider`/`judge_2_provider` fields on `ClaimRequest`, validated against `get_llm()`'s provider allowlist; two `st.selectbox` dropdowns in the dashboard's ingestion panel; `evaluate_decision()` accepts explicit providers, falling back to `provider_for_role()` when unset.
- [ ] Global hot-swappable default: an admin surface (e.g. `PUT /config/providers`) backed by `pydantic-settings` and/or a config table — a "vendor is down, reroute now" lever with no restart. Later increment.

### 7 — ⚪ High-Value Court (Phase 1.G) — planned
Design: [docs/architecture/high_value_court.md](docs/architecture/high_value_court.md).
- [ ] Prerequisite: Part B (deterministic evidence checks), including currency conversion to USD.
- [ ] Routing by amount in USD: < $1,000 today's pipeline; $1,000–$5,000 the court; > $5,000 human review (policy). `HIGH_VALUE_THRESHOLD_USD`, default 1000.
- [ ] Four judges from four different model families, all must APPROVE (families to confirm on Groq and measure with the eval).
- [ ] Superior judge (candidate: Gemini Pro, check the trial credit covers it): on any rejection it can only confirm the REJECT or route to human review. **Never approves over a rejection** (user decision).
- [ ] Pick the models with the Promptfoo eval; grade the whole court as one provider on new $1,000–$5,000 cases, repeats spread over time. Acceptance bar: zero false approvals.

### 8 — ⚪ Deterministic Confidence Layer (Phase 2)
- [ ] Integrate the fuzzy-scoring layer and the Belief Rule Base alongside the AI Judge, so critical transactions (`execute_refund`, `validate_fraud_score`) require double approval — probabilistic (LLM judge) *and* symbolic (rule base) — before auto-approving.

### 9 — ⚪ Quality Drift Detection (Phase 3)
- [ ] Implement the async monitor with a statistical filter (EWMA default, CUSUM/Page-Hinkley/Kalman as options) to detect whether model responses are degrading over time. Runs off the critical path — never blocks transaction processing.

### 10 — ⚪ AWS (Phase 6, secondary target)
- [ ] Configure IAM credentials and AWS Bedrock access (least privilege, VPC PrivateLink).
- [ ] Swap the embeddings module to Amazon Titan behind `get_embeddings()`.
- [ ] Serverless topology: AWS API Gateway + SQS + Lambda + serverless PostgreSQL (Neon with pgvector).
