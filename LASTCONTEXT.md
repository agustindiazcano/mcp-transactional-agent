# Last Context — Current State (2026-09-23)

Only what is current: read this first in every session. When an item here is done or superseded, move the session's detailed notes to `docs/worklog/` and keep this file short. History: [docs/worklog/](docs/worklog/).

## Where things stand
- **`main`** has everything through PR #51 (`feat/gcp-terraform-base`): Vertex AI works end to end, and the GCP deploy's Terraform base is merged. Details: `docs/worklog/2026-09-22_to_2026-09-23.md`.
- **GCP deploy: steps 1–5 of 10 done.** State bucket, Terraform base, Artifact Registry repo, service accounts, and the 4 images pushed (tag `b0e7dbe`). Details in the worklog's "GCP deploy" sections. Next is step 6, Cloud SQL (the first resource that costs money while running).
  - **The user is learning Terraform/GCP: go one small explained step per turn** (the user writes the `.tf` edits and runs `plan`/`apply`/`docker` in their own terminal; review each plan before `apply`).
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
  - Terraform in `infra/`, state in `gs://project-e0ad10c9-0b2f-4dc0-ac6-tfstate` (versioned), no secrets in the state.
  - IAM only through `google_project_iam_member` (additive), never `_binding` or `_policy`. Renames go through a `moved` block, never destroy + create.
  - Always `plan -out=tfplan` then `apply tfplan`.
  - Secrets in Secret Manager, added by hand (never through Terraform variables).
  - A `demo-up` / `demo-down` switch: stop Cloud SQL and scale the worker and sweeper to 0. Cloud SQL is the only real idle cost.
- **Messaging for the cloud demo: CloudAMQP free plan (confirmed).** No code change; only `RABBITMQ_URL` changes. The instance is **LavinMQ** (`*.lmq.cloudamqp.com`, AMQP 0-9-1), not RabbitMQ: verify it with the first real claim in the cloud.
- **CV and public claims:** list Google Cloud, Cloud SQL, Terraform and CI/CD only once each one runs. Today only CI exists; CD means a merge to `main` deploys to Cloud Run through Workload Identity Federation. Vertex AI can already be listed.
- **Evaluation tools:** Promptfoo and Langfuse next, Ragas later. LangSmith and TruLens are not adopted.
- **Resolver agent (agent B):** it changes the Phase 1.E design, so it needs the user's go-ahead.
- **Public docs are recruiter-facing:** no "human in the loop" anecdotes, and nothing presented as done before it is.

## Waiting on the user
| # | | What | Status |
|---|---|---|---|
| 1 | 🟡 | Decide when to start step 6 (Cloud SQL): it's the slowest step (5–10 min to create) and costs ~$8–10/month while on | ⬜ |
| 2 | 🟢 | Rotate the CloudAMQP password before the cloud demo goes live (the URL was pasted in a session) | optional |
| 3 | 🟢 | Check the `agustin-google-cloud` service account's **Keys** tab; delete any unused JSON key | ⬜ |
| 4 | 🟢 | Rotate the Groq key (printed once in a session's output; low risk, local only) | optional |
| 5 | 🟢 | GitHub profile text: says 232 tests, the count is 248 | ⬜ |
| 6 | 🟢 | Langfuse Cloud account (free tier), keys in `.env` | ⬜ |
| 7 | 🟢 | Settings → Branches: branch protection on `main`, requiring the CI checks | ⬜ |

## Next, in order
1. **GCP deploy (demo environment)**, step by step with the user:
   - ✅ 1. State bucket. ✅ 2. Terraform base. ✅ 3. Artifact Registry repo `app-images`. ✅ 4. Service accounts (`worker-sa`, `gateway-sa`, `mcp-server-sa`, `dashboard-sa`).
   - ✅ 5. The 4 images (gateway, worker, mcp_server, dashboard) are in `us-central1-docker.pkg.dev/project-e0ad10c9-0b2f-4dc0-ac6/app-images/<service>:b0e7dbe` (the `main` commit they were built from). `sweeper` and `migrate` reuse the `worker` image with a different command.
   - ⬜ **6. Cloud SQL for PostgreSQL + pgvector, smallest tier** ← next. Concepts to cover: private IP vs. the Cloud SQL Auth Proxy / connector, DB users, Alembic as a Cloud Run job. Alembic runs as a Cloud Run job; confirm the revision with the user first (CLAUDE.md §8).
   - ⬜ 7. Secret Manager: Groq key, MCP client tokens, DB password (`rabbitmq-url` already exists). Narrow `secretAccessor` from project-wide to per-secret grants.
   - ⬜ 8. Cloud Run: gateway, mcp_server and dashboard as HTTP services; worker and sweeper as always-on consumers (how to host a non-HTTP consumer on Cloud Run is decided here and shown to the user before applying). Each service runs as its own SA.
   - ⬜ 9. One real claim end to end in the cloud (also validates LavinMQ); the `demo-up` / `demo-down` switch.
   - ⬜ 10. CD with GitHub Actions + Workload Identity Federation (no keys in GitHub), and the Locust load test against Cloud Run. Before it, reorder the Dockerfiles to install dependencies before `COPY src` (today every code change reruns the full `pip install`: 2–4 min per build and a fresh ~170 MB layer per push).
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
  - On the free-trial credit, with billing enabled and a $20 budget alert (50/90/100%, credits excluded).
  - APIs enabled: Vertex AI, Cloud Run, Cloud SQL Admin, Artifact Registry, Secret Manager, IAM. Container Scanning is **not** enabled (it's paid).
  - ADC is logged in (`gcloud auth application-default login`).
  - Created: the state bucket (by hand), the `app-images` repo and the 4 service accounts (Terraform), the `rabbitmq-url` secret (by hand), and the 4 images tagged `b0e7dbe` (580 MB in the repo; the free tier is 0.5 GB, so ~$0.01/month). Nothing runs yet.
  - Docker on this laptop pushes to Artifact Registry through `gcloud auth configure-docker us-central1-docker.pkg.dev` (a credential helper in `~/.docker/config.json`, no stored password).
  - Also present, not ours: the default Compute SA (has Editor; never let Cloud Run fall back to it) and `agustin-google-cloud` (created by the user earlier).
- **Tools:** Terraform v1.16.2, google provider v8.4.0 (pinned in `infra/.terraform.lock.hcl`). `gcloud` works (open a new terminal if it isn't found).
- **Local stack:** `.env` is back on `LLM_PROVIDER=mock`. For real Vertex: `docker compose -f docker-compose.yml -f docker-compose.gcp.yml up -d` with `LLM_PROVIDER=vertex`. For load or chaos tests: `docker-compose.chaos.yml` (mocks).
- The dev DB holds test rows (prefixes `chaos-`, `tput-`, `prof-`, `vertex-e2e-`).

## Gotchas that still apply
- Inside containers, `VERTEX_PROJECT` must be set, because there's no gcloud config to resolve it from. A Vertex auth failure shows up as judges failing closed to `REJECT`, not as an auth error.
- Gemini 3.x models return 404 on regional Vertex endpoints: chat must use `global`.
- After migrating the dev DB from the host, rebuild every image built from `worker.Dockerfile` (`worker`, `sweeper`, `migrate`) before `docker compose up`.
- The chaos test kills the worker by its fixed name (`agentic_worker`), so run it without `docker-compose.scale.yml`.
- Measure scaling with `docker pause`, not `stop`/`start`: a restarted worker re-imports LangChain inside the measured window.
- `updated_at` uses `clock_timestamp()`, because the worker holds a transaction open, so `now()` would stamp it too early.
- `infra/backend.tf` can't use variables (the backend loads first), so the bucket name is written out there.
- The `!` prefix only works in the Claude Code prompt, not in a normal PowerShell window (there `!` means NOT).
- The hooks in `.claude/settings.json` use `$CLAUDE_PROJECT_DIR`; a relative path blocked every tool call once the session's directory moved into `infra/`. Claude can't edit its own hooks: the user does.
