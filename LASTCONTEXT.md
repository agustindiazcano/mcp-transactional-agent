# Last Context — Current State (2026-09-23)

Only what is current: read this first in every session. When an item here is done or superseded, move the session's detailed notes to `docs/worklog/` and keep this file short. History: [docs/worklog/](docs/worklog/).

## Where things stand
- **`main`** has everything through PR #46: real refund execution, orders and read tools, CI with an 80% coverage gate, mock mode for every LLM role, the chaos test, the processing throughput test, and the rewritten AI-Assisted Development section.
- **Open branch `docs/readme-index-and-eval`**, pushed, PR not opened yet (the user opens it; there's no `gh` CLI): https://github.com/agustindiazcano/mcp-transactional-agent/compare/main...docs/readme-index-and-eval
  - README table of contents, and a top-level "LLM Evaluation & Observability" section.
  - The Documentation Index completed and stale docs cleaned.
  - This file split into a short current state plus `docs/worklog/`.
- **Tests:** 239 (189 unit + 50 integration), 84% coverage. `ruff` and `mypy --strict src` are clean.
- **Headline numbers:**
  - Chaos test: 2,000 claims, worker killed twice and RabbitMQ restarted → 0 lost, 0 double refunds.
  - Throughput, mocked LLMs, 4-core laptop: 9.2 claims/s with 1 worker → 19.6 with 8.
  - Ingestion: P95 of 87 ms.
  - Cost: ~$0.0004 per real transaction.

## Decisions in force
- **Evaluation tools:** Promptfoo and Langfuse next, Ragas later. LangSmith and TruLens are not adopted.
- **GCP deploy:**
  - Terraform in `infra/`, with state in a GCS bucket and no secrets in the state.
  - A demo on/off switch: stop Cloud SQL and scale the worker/sweeper to 0 when idle. Cloud Run scales to zero on its own, and the Vertex API only bills per call.
  - A budget alert in Billing.
- **Messaging for GCP: still open.** A managed RabbitMQ free tier (no code change) is the recommendation, against Pub/Sub, which needs the retry and idempotency contract re-validated. The user must confirm (CLAUDE.md §5f).
- **Resolver agent (agent B):** it changes the Phase 1.E design, so it needs the user's go-ahead.
- **Public docs are recruiter-facing:** no "human in the loop" anecdotes, and nothing presented as done before it is.

## Waiting on the user
- Open the `docs/readme-index-and-eval` PR, and update the GitHub profile text (it says 232 tests; the count is 239).
- **GCP:**
  - the project ID and region (suggested `us-central1`);
  - `gcloud` and Terraform installed;
  - a run of `! gcloud auth login` and `! gcloud auth application-default login`.
- **Evaluation:** a Langfuse Cloud account (free tier), with its keys in `.env`.
- **In `.env`:** unset `LANGCHAIN_TRACING_V2`. It's the source of the worker's LangSmith `403` warnings.
- **Settings → Branches:** branch protection on `main`, requiring the CI checks.

## Next, in order
1. **GCP deploy with Vertex AI:**
   - Vertex provider: declare `langchain-google-vertexai`, move the model to config (it's still `gemini-1.5-pro`), and route `vertex` embeddings to Vertex.
   - Terraform: Cloud SQL with pgvector, Artifact Registry, Cloud Run, and Secret Manager.
   - CI/CD with Workload Identity Federation.
   - Cloud numbers.
2. **LLM evaluation:** Promptfoo with about 100 labeled cases (the user reviews the labels), plus Langfuse.
3. **Part B, evidence for the judges:**
   - fetch `get_order` and `get_refund_history` through MCP before judging;
   - a deterministic check that the amount doesn't exceed the order, the currency matches, and the order belongs to the user, failing closed to `PENDING_HUMAN_REVIEW`;
   - close the DB transaction the worker holds open across the judges and the MCP call.
4. **Resolver agent.** Also listed in `PENDING.md`: MCP server replicas, the dead-letter queue, not retrying 4xx responses, and Gemini ignoring `temperature=0`.

## Environment state
- The local stack runs in **chaos mode**: `docker-compose.chaos.yml`, with mock LLMs, the MCP rate limit lifted, and one `agentic_worker`. Go back to normal with `docker compose up -d`.
- The dev DB holds the test rows (prefixes `chaos-`, `tput-`, `prof-`).

## Gotchas that still apply
- After migrating the dev DB from the host, rebuild every image built from `worker.Dockerfile` (`worker`, `sweeper`, `migrate`) before `docker compose up`.
- The chaos test kills the worker by its fixed name (`agentic_worker`), so run it without `docker-compose.scale.yml`.
- Measure scaling with `docker pause`, not `stop`/`start`: a restarted worker re-imports LangChain inside the measured window.
- `updated_at` uses `clock_timestamp()`, because the worker holds a transaction open, so `now()` would stamp it too early.
