# Last Context — Current State (2026-09-23)

Only what is current: read this first in every session. When an item here is done or superseded, move the session's detailed notes to `docs/worklog/` and keep this file short. History: [docs/worklog/](docs/worklog/).

## Where things stand
- **`main`** has everything through PR #48 (README index and evaluation section, worklog split).
- **Open branch `feat/vertex-provider`**, pushed, PR not opened yet (the user opens it; there's no `gh` CLI): https://github.com/agustindiazcano/mcp-transactional-agent/compare/main...feat/vertex-provider
  - Vertex AI works end to end: real claims through the containerized stack, with Judge 1, the Supreme Court and the embeddings on Vertex, and the refund executed. Details: `docs/worklog/2026-09-22_to_2026-09-23.md`.
- **Tests:** 248 (198 unit + 50 integration), 85% coverage. `ruff` and `mypy --strict src` are clean.
- **Headline numbers:**
  - Chaos test: 2,000 claims, worker killed twice and RabbitMQ restarted → 0 lost, 0 double refunds.
  - Throughput, mocked LLMs, 4-core laptop: 9.2 claims/s with 1 worker → 19.6 with 8.
  - Ingestion: P95 of 87 ms.
  - Real claim on Vertex: 6.6 s end to end.
  - Cost: ~$0.0004 per transaction on AI Studio (2026-09-21). The Vertex cost is pending the model benchmark.

## Decisions in force
- **Vertex setup:** `langchain-google-genai` with `vertexai=True`, not the deprecated `ChatVertexAI`. Chat on `global`, embeddings on `us-central1`. ADC only, never an API key.
- **Judges stay asymmetric:** Judge 1 and Judge 2 come from different model families. Groq stays as an off-GCP fallback.
- **Determinism is measured, not assumed:** verdict stability over repeated runs, since `claude-sonnet-5` rejects `temperature` and Gemini 3.5 is a thinking model.
- **Evaluation tools:** Promptfoo and Langfuse next, Ragas later. LangSmith and TruLens are not adopted.
- **GCP deploy:** Terraform in `infra/` (state in a GCS bucket, no secrets in it), a demo on/off switch, and a budget alert in Billing.
- **Messaging for GCP: still open.** A managed RabbitMQ free tier (no code change) is recommended over Pub/Sub. The user must confirm (CLAUDE.md §5f).
- **Resolver agent (agent B):** it changes the Phase 1.E design, so it needs the user's go-ahead.
- **Public docs are recruiter-facing:** no "human in the loop" anecdotes, and nothing presented as done before it is.

## Waiting on the user
1. Open and merge the `feat/vertex-provider` PR.
2. Set a **budget alert** in GCP Billing: `.env` now has `LLM_PROVIDER=vertex`, so every local claim is a paid call.
3. Optional: rotate the Groq key. It was printed once in a session's output; low risk, local only.
4. Update the GitHub profile text: it says 232 tests, and the count is 248.
5. Decide the messaging for GCP: managed RabbitMQ or Pub/Sub.
6. For Model Garden: enable the Claude models in the Vertex console (accept the terms).
7. A Langfuse Cloud account (free tier), with its keys in `.env`.
8. Settings → Branches: branch protection on `main`, requiring the CI checks.

## Next, in order
1. **Part B, evidence for the judges.** A real run rejected a valid claim for lack of the purchase date.
   - Fetch `get_order` and `get_refund_history` through MCP before judging.
   - A deterministic check (amount ≤ order, same currency, order owned by the user), failing closed to `PENDING_HUMAN_REVIEW`.
   - Close the DB transaction the worker holds open across the judges.
2. **`feat/vertex-model-garden`:**
   - Claude (`claude-sonnet-5`, `claude-haiku-4-5`) on Vertex, behind the factory.
   - A verdict-stability check.
   - `scripts/cost_benchmark.py`, printing a Markdown table of latency, tokens and cost at prices fetched on the run date. Then fill in the README's Vertex cost.
3. **GCP deploy:** Terraform for Cloud SQL (pgvector), Artifact Registry, Cloud Run and Secret Manager; CI/CD with Workload Identity Federation; cloud load numbers.
4. **LLM evaluation:** Promptfoo with about 100 labeled cases (the user reviews the labels; the benchmark claims seed the set), plus Langfuse.
5. **Reliability backlog** in `PENDING.md`: MCP server replicas, the dead-letter queue, not retrying 4xx responses, and a stepped ingestion load test.
6. Then Phase 1.E (a real primary agent), 1.F, 2 and 3, and AWS.

## Environment state
- The local stack runs in **normal mode with real Vertex**: `docker compose -f docker-compose.yml -f docker-compose.gcp.yml up -d`, and `.env` has `LLM_PROVIDER=vertex`. Claims now cost real money. For load or chaos tests, switch to `docker-compose.chaos.yml` (mocks).
- The dev DB holds test rows (prefixes `chaos-`, `tput-`, `prof-`, `vertex-e2e-`).

## Gotchas that still apply
- Inside containers, `VERTEX_PROJECT` must be set, because there's no gcloud config to resolve it from. A Vertex auth failure shows up as judges failing closed to `REJECT`, not as an auth error.
- After migrating the dev DB from the host, rebuild every image built from `worker.Dockerfile` (`worker`, `sweeper`, `migrate`) before `docker compose up`.
- The chaos test kills the worker by its fixed name (`agentic_worker`), so run it without `docker-compose.scale.yml`.
- Measure scaling with `docker pause`, not `stop`/`start`: a restarted worker re-imports LangChain inside the measured window.
- `updated_at` uses `clock_timestamp()`, because the worker holds a transaction open, so `now()` would stamp it too early.
