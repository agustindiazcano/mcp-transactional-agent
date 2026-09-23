# Last Context — Current State (2026-09-23)

Only what is current: read this first in every session. When an item here is done or superseded, move the session's detailed notes to `docs/worklog/` and keep this file short. History: [docs/worklog/](docs/worklog/).

## Where things stand
- **`main`** has everything through PR #49 (`feat/vertex-provider`): Vertex AI works end to end. Real claims ran through the containerized stack with Judge 1, the Supreme Court and the embeddings on Vertex, and the refund was executed. Details: `docs/worklog/2026-09-22_to_2026-09-23.md`.
- **Open branch `docs/model-catalog`**, pushed, PR not opened yet (the user opens it; there's no `gh` CLI): https://github.com/agustindiazcano/mcp-transactional-agent/compare/main...docs/model-catalog
  - It holds 4 commits pushed to `feat/vertex-provider` after PR #49 merged, plus this file: the role-labeled model catalog in `.env.example` (Claude/Grok marked `[ref]`) and the benchmark rescoped to Gemini + Groq.
- **Tests:** 248 (198 unit + 50 integration), 85% coverage. `ruff` and `mypy --strict src` are clean.
- **Headline numbers:**
  - Chaos test: 2,000 claims, worker killed twice and RabbitMQ restarted → 0 lost, 0 double refunds.
  - Throughput, mocked LLMs, 4-core laptop: 9.2 claims/s with 1 worker → 19.6 with 8.
  - Ingestion: P95 of 87 ms.
  - Real claim on Vertex: 6.6 s end to end.
  - Cost: ~$0.0004 per transaction on AI Studio (2026-09-21). The Vertex cost is pending the model benchmark.

## Decisions in force
- **Vertex setup:** `langchain-google-genai` with `vertexai=True`, not the deprecated `ChatVertexAI`. Chat on `global`, embeddings on `us-central1`. ADC only, never an API key.
- **Judges stay asymmetric:** Judge 1 on Gemini (Vertex), Judge 2 on GPT-OSS (Groq). Groq is the only non-Gemini family available and also hosts the Prompt Guard.
- **Only Gemini (Vertex) and Groq models:** the GCP free-trial credit doesn't cover partner models; Model Garden refused to enable Claude. Claude and Grok stay as reference prices in `.env.example`.
- **Determinism is measured, not assumed:** verdict stability over repeated runs, since the Gemini 3.x Flash models think before answering.
- **Two environments, same code:**
  - Development runs locally (Docker: local RabbitMQ and Postgres, `LLM_PROVIDER=mock` day to day, `vertex` only to validate).
  - Google Cloud is a **demo-only** environment, switched on to show it and off afterwards.
- **GCP deploy:**
  - Terraform in `infra/`, with state in a GCS bucket and no secrets in the state.
  - Secrets in Secret Manager.
  - A `demo-up` / `demo-down` switch: stop Cloud SQL and scale the worker and sweeper to 0. Cloud SQL is the only real idle cost.
  - A budget alert in Billing.
- **Messaging for the cloud demo:** option A, CloudAMQP free plan (no code change; only `RABBITMQ_URL` changes, stored in Secret Manager), is recommended over a RabbitMQ VM (needs VPC) or Pub/Sub (retry and idempotency contract must be re-validated). **Awaiting the user's confirmation** (CLAUDE.md §5f).
- **CV and public claims:** list Google Cloud, Cloud SQL, Terraform and CI/CD only once each one runs. Today only CI exists; CD means a merge to `main` deploys to Cloud Run through Workload Identity Federation. Vertex AI can already be listed.
- **Evaluation tools:** Promptfoo and Langfuse next, Ragas later. LangSmith and TruLens are not adopted.
- **Resolver agent (agent B):** it changes the Phase 1.E design, so it needs the user's go-ahead.
- **Public docs are recruiter-facing:** no "human in the loop" anecdotes, and nothing presented as done before it is.

## Waiting on the user
| # | | What | Status |
|---|---|---|---|
| 1 | 🔴 | Confirm messaging option A, then create a CloudAMQP free instance (GCP `us-central1`) and hand over its URL for Secret Manager | ⬜ |
| 2 | 🔴 | Install Terraform (`winget install Hashicorp.Terraform`), then restart the terminal so `gcloud` is on PATH too | ⬜ |
| 3 | 🔴 | Budget alert in GCP Billing (e.g. $20, alerts at 50/90/100%) | ⬜ |
| 4 | 🟡 | Open and merge the `docs/model-catalog` PR | ⬜ |
| 5 | 🟡 | Switch `.env` back to `LLM_PROVIDER=mock` for day-to-day dev (every local claim on `vertex` is a paid call) | ⬜ |
| 6 | 🟢 | Rotate the Groq key (printed once in a session's output; low risk, local only) | optional |
| 7 | 🟢 | GitHub profile text: says 232 tests, the count is 248 | ⬜ |
| 8 | 🟢 | Langfuse Cloud account (free tier), keys in `.env` | ⬜ |
| 9 | 🟢 | Settings → Branches: branch protection on `main`, requiring the CI checks | ⬜ |

## Next, in order
1. **GCP deploy (demo environment)**, starting once items 1–3 above are done:
   1. Terraform base in `infra/`: GCS state bucket, the Artifact Registry repo, and least-privilege service accounts (the worker gets Vertex user, secret accessor and Cloud SQL client only).
   2. Build and push the 4 images (gateway, worker, mcp_server, dashboard) to Artifact Registry.
   3. Cloud SQL for PostgreSQL + pgvector, smallest tier. Alembic runs as a Cloud Run job; confirm the revision with the user first (CLAUDE.md §8).
   4. Secret Manager: Groq key, MCP client tokens, DB password, CloudAMQP URL.
   5. Cloud Run: gateway, mcp_server and dashboard as HTTP services; worker and sweeper as always-on consumers (how to host a non-HTTP consumer on Cloud Run is decided here and shown to the user before applying). On Cloud Run, Vertex auth is the service account, with no mounted credentials.
   6. One real claim end to end in the cloud; the `demo-up` / `demo-down` switch.
   7. CD with GitHub Actions + Workload Identity Federation (no keys in GitHub), and the Locust load test against Cloud Run.
2. **Part B, evidence for the judges** (independent of the deploy, can run in parallel). A real run rejected a valid claim for lack of the purchase date.
   - Fetch `get_order` and `get_refund_history` through MCP before judging.
   - A deterministic check (amount ≤ order, same currency, order owned by the user), failing closed to `PENDING_HUMAN_REVIEW`.
   - Close the DB transaction the worker holds open across the judges.
3. **`feat/model-benchmark`** (Gemini 3.1/3.5 Flash-Lite and 3.8 Flash on Vertex, GPT-OSS 20B on Groq): a verdict-stability check, and `scripts/cost_benchmark.py` printing a Markdown table of latency, tokens and cost at prices fetched on the run date (under $1). Then fill in the README's Vertex cost.
4. **LLM evaluation:** Promptfoo with about 100 labeled cases (the user reviews the labels; the benchmark claims seed the set), plus Langfuse.
5. **Reliability backlog** in `PENDING.md`: MCP server replicas, the dead-letter queue, not retrying 4xx responses, and a stepped ingestion load test.
6. Then Phase 1.E (a real primary agent), 1.F, 2 and 3, and AWS.

## Environment state
- **GCP project `project-e0ad10c9-0b2f-4dc0-ac6`:**
  - On the free-trial credit, with billing enabled.
  - APIs already enabled: Vertex AI, Cloud Run, Cloud SQL Admin, Artifact Registry, Secret Manager, IAM.
  - ADC is logged in (`gcloud auth application-default login`).
  - Nothing is deployed yet.
- **Tools:**
  - `gcloud` is installed at `C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd`, but it wasn't on PATH in the last session.
  - Terraform is not installed.
- **The local stack runs in normal mode with real Vertex:** `docker compose -f docker-compose.yml -f docker-compose.gcp.yml up -d`, and `.env` has `LLM_PROVIDER=vertex` and `VERTEX_PROJECT` set. For load or chaos tests, switch to `docker-compose.chaos.yml` (mocks).
- The dev DB holds test rows (prefixes `chaos-`, `tput-`, `prof-`, `vertex-e2e-`).

## Gotchas that still apply
- Inside containers, `VERTEX_PROJECT` must be set, because there's no gcloud config to resolve it from. A Vertex auth failure shows up as judges failing closed to `REJECT`, not as an auth error.
- Gemini 3.x models return 404 on regional Vertex endpoints: chat must use `global`.
- After migrating the dev DB from the host, rebuild every image built from `worker.Dockerfile` (`worker`, `sweeper`, `migrate`) before `docker compose up`.
- The chaos test kills the worker by its fixed name (`agentic_worker`), so run it without `docker-compose.scale.yml`.
- Measure scaling with `docker pause`, not `stop`/`start`: a restarted worker re-imports LangChain inside the measured window.
- `updated_at` uses `clock_timestamp()`, because the worker holds a transaction open, so `now()` would stamp it too early.
