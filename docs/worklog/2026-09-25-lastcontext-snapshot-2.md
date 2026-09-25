# Last Context Snapshot — 2026-09-25 (midday)

A full copy of `LASTCONTEXT.md` as it stood after PR #72 but before #73, the direct-to-main credits correction, and the Phase 1.E schema/proposer work. Superseded items are recorded here.

---

# Last Context — Current State (2026-09-25)

Only what is still open: read this first in every session. When an item here is done, move it to `docs/worklog/` and take it out of this file. What was done up to earlier today: [docs/worklog/2026-09-25-lastcontext-snapshot.md](docs/worklog/2026-09-25-lastcontext-snapshot.md). Older history: [docs/worklog/](docs/worklog/).

## Where things stand
- **`main`** has everything through PR #72: Part B / evidence check (#69), the `session-start-hook` that injects this file + `PENDING.md` into every session (#70), the cloud-environment setup (#71), and the self-correction fix + doc sync (#72, below). Branch `docs/high-value-court` (Phase 1.G design) is merged (#68).
- **This session (2026-09-25) ran in Claude Code on the web** — an isolated cloud container, not the user's laptop. Three things came out of it, all on `main` now:
  1. **Cloud test environment (`.claude/hooks/session-start-env.sh`, PR #71):** a second `SessionStart` hook entry (alongside the existing LASTCONTEXT/PENDING one) that installs PostgreSQL 16 + pgvector and RabbitMQ, installs the project's dev extras, and migrates both the dev and `_test` databases to head — every time a cloud session starts, since neither service survives between shell contexts in that container. No Docker daemon is available there, so this replaces `docker compose` for running the test suite only. Validated: 360/360 tests passing, `ruff`/`mypy --strict` clean, confirmed idempotent. **Cloud sessions still have no LLM API keys** (only `LLM_PROVIDER=mock` works) and can't reach Docker Compose, GCP, or `gcloud` — that work still needs the user's laptop or `claude remote-control`.
  2. **Self-correction re-vote bug, fixed (commit `1645477`, PR #72):** `worker.py`'s retry loop called `evaluate_decision()` (which already runs the full Judge 1 + Judge 2 + Supreme Court cascade internally) up to `MAX_LLM_RETRIES` times on REJECT — but the primary agent's proposal is still hardcoded, so every retry sent the judges the *exact same input*. That's a re-vote, not correction: with judge verdicts not perfectly stable between runs (the €4,800 over-limit claim was approved 4/5 times in the 2026-09-24 benchmark), a p-probability wrong approval per round became 1-(1-p)³ over 3 rounds (p=0.10 → ~27%). Now `evaluate_decision()` is called exactly once per claim. `CLAUDE.md` (and its mirrors `GEMINI.md`/`AGENTS.md`, which were also stale on Part B and are now byte-identical to `CLAUDE.md` again), `README.md`, and `docs/architecture/api_abuse_protection.md` are corrected to match. This becomes a real retry loop again once Phase 1.E's proposer can revise a rejected proposal from judge feedback.
  3. **PR-merge timing gap, found and fixed (PR #72):** #71 merged the instant the branch was at its cloud-environment-setup commit — before the next push (the re-vote fix) had finished landing on the branch. The result: `main` briefly still had the original bug even though this session had reported it fixed. Caught by checking `git merge-base --is-ancestor <fix commit> origin/main` before trusting "pushed" to mean "merged"; fixed by opening a fresh PR (#71 was already closed) with the missing commits. Lesson folded into the gotcha below.
- **The user received $100 in Anthropic cloud credits.** Correction (2026-09-25): these are for running Claude Code cloud sessions/compute, not LLM provider API calls. Phase 1.E's real LLM calls (the proposer) and its Promptfoo eval run on a separate budget (Gemini/Groq/Vertex usage) — don't conflate the two.
- **Cloud-session gotchas for next time:**
  - This session's designated branch (`claude/awesome-wright-bipend`) had its remote copy deleted once its PR merged, twice today (#71, then #72). A fresh cloud session reusing that branch name must rebuild it from current `main` (`git fetch origin main && git checkout -B claude/awesome-wright-bipend origin/main`), not assume old history is still there.
  - **After any push meant for a PR, verify it actually landed** — `git merge-base --is-ancestor <commit> origin/main` — rather than trusting an earlier "PR was created" notification. A PR can merge between two pushes to the same branch; the second push then needs its own new PR, since a merged/closed PR can't be reopened onto.
  - A cloud session cannot edit `.claude/settings.json` itself (blocked by the harness's self-modification guard) — any new hook registration needs the user to hand-edit that one file.
- **The GCP demo state is whatever it was left at earlier** — this session had no `gcloud`/GCP access to check or change it. Last known (before this session): **DOWN** (Cloud SQL `STOPPED`, both worker pools at 0); the first `demo-up` was still untested.
  - Dashboard: https://dashboard-993240087609.us-central1.run.app · Gateway: https://gateway-993240087609.us-central1.run.app
  - **The user is learning Terraform/GCP: one small explained step per turn.** Claude writes the `.tf`, runs `validate`/`plan` and commits; the user runs `apply`. Review each plan before `apply`.
- **Part B (evidence check) is merged** (`feat/judge-evidence`, PR #69). Before the judges, the worker fetches `get_order` + `get_refund_history` through MCP and checks them in code (owner, currency, refund + earlier refunds ≤ order, ≤ $5,000 in USD at static ECB rates). A failure or an MCP outage → `PENDING_HUMAN_REVIEW`, no LLM call, ACK. A few Part B follow-ups are still open in `PENDING.md` §1 (cloud allowlist check, chaos re-run, dev DB reseed, eval re-run for `b2-reject-04`).

## Decisions in force
- **Vertex setup:** `langchain-google-genai` with `vertexai=True`, not the deprecated `ChatVertexAI`. Chat on `global`, embeddings on `us-central1`. ADC only, never an API key.
- **Judges stay asymmetric:** Judge 1 on Gemini (Vertex), Judge 2 on GPT-OSS (Groq). Groq is the only non-Gemini family available and also hosts the Prompt Guard.
- **Only Gemini (Vertex) and Groq models:** the GCP free-trial credit doesn't cover partner models; Model Garden refused to enable Claude. Claude and Grok stay as reference prices in `.env.example`.
- **Determinism is measured, not assumed:** verdict stability over repeated runs, since the Gemini 3.x Flash models think before answering.
- **Two environments, same code:**
  - Development runs locally (Docker: local RabbitMQ and Postgres, `LLM_PROVIDER=mock` day to day, `vertex` only to validate).
  - Google Cloud is a **demo-only** environment, switched on to show it and off afterwards.
- **GCP deploy:**
  - Terraform in `infra/`, state in `gs://project-e0ad10c9-0b2f-4dc0-ac6-tfstate` (versioned). No secrets in the state, **with one accepted exception (user decision, 2026-09-23):** the Cloud SQL `app` password is generated by Terraform (`random_password`), so it and the `database-url` secret version live in the state. The bucket is private.
  - IAM only through `google_project_iam_member` (additive), never `_binding` or `_policy`. Renames go through a `moved` block, never destroy + create. Secret access is per secret only (`google_secret_manager_secret_iam_member`).
  - Always `plan -out=tfplan` then `apply tfplan`, run from `infra/`.
  - External secrets (API keys, broker URL, tokens) go into Secret Manager by hand, never through Terraform variables. Only values Terraform generates itself (the DB password) are written by Terraform.
  - Cloud SQL is reached only through Cloud Run's built-in connector (public IP, no authorized networks, `ENCRYPTED_ONLY`); no VPC. Migrations: `gcloud run jobs execute migrate --region us-central1 [--args=current] --wait`; confirm the revision with the user first (CLAUDE.md §8). Migrations stay manual (CD deploys images only).
  - **Demo switch:** `var.demo_up` (`scripts/demo-up.ps1` / `demo-down.ps1`). `false` stops Cloud SQL and scales both worker pools to 0.
  - **Cloud Run:** consumers are worker pools (no HTTP port). The MCP server is `allUsers` at the Cloud Run layer; the dashboard and gateway are public until a login exists.
  - **CD:** Terraform ignores the image; CD deploys with `gcloud` through Workload Identity Federation (`github-deployer-sa`).
- **Messaging for the cloud demo: CloudAMQP free plan (LavinMQ).**
- **CV and public claims:** list a technology only once it runs.
- **Evaluation tools:** Ragas later. LangSmith and TruLens are not adopted.
- **Resolver agent (agent B):** it changes the Phase 1.E design, so it needs the user's go-ahead.
- **High-Value Court (Phase 1.G), planned (user decision 2026-09-24):** refunds of $1,000–$5,000 (in USD, after conversion) need four judges from four model families to all approve; a superior judge (candidate Gemini Pro) reviews any rejection and can only confirm it or route to a human, **never approve over a rejection**. After Part B (now met). Design: `docs/architecture/high_value_court.md`.
- **Public docs are recruiter-facing:** no "human in the loop" anecdotes, and nothing presented as done before it is.
- **Phase 1.E order (2026-09-25):** single-turn first (claim text → validated proposal → judges), not the multi-turn chat variant. Chat is a separate, later increment on top of it.

## Waiting on the user
| # | | What | Status |
|---|---|---|---|
| 1 | 🟡 | Decide the public API protection: which option, and when ([analysis](docs/architecture/api_abuse_protection.md)). Until then, `demo-down` when not demoing | ⬜ |
| 2 | 🟢 | Rotate the Groq key (printed once in a session's output; low risk, local only) | optional |
| 3 | 🟢 | GitHub profile text: says 232 tests, the count is 360 | ⬜ |
| 4 | 🟢 | Settings → Branches: branch protection on `main`, requiring the CI checks | ⬜ |
| 5 | 🟢 | `.claude/settings.json`'s `SessionStart` array now has two entries (LASTCONTEXT/PENDING injection + the new test-environment hook) — no action needed, just noting a cloud session can't edit that file itself | done |

## Next, in order
1. 🔴 **Phase 1.E, single-turn agent** (user decision, 2026-09-25): replace `worker.py`'s hardcoded `mock_primary_action = "execute_refund"` with a real primary-agent LLM call. Estimate ~10–14h. Steps: proposal schema (Pydantic, `extra="forbid"`), the proposer LLM in `src/agents/`, wiring it into `worker.py` in place of the mock, a real self-correction loop (now that a proposal can actually change), a `NEEDS_CLARIFICATION` outcome, then a Promptfoo eval (~30 labeled claims) and a real run on Vertex. Real LLM cost here is Gemini/Groq/Vertex usage — a separate budget from the Anthropic cloud credits, which pay for Claude Code sessions, not this.
2. 🟡 Re-run the eval: `b2-reject-04` ($3,000 refund on a "$30 charger") must become impossible to approve now that Part B is live. Then the RAG chunker fix (headings separated from their rules, found by the eval) and re-ingestion.
3. 🟡 **GCP leftovers:** test the first `demo-up`; Locust load test against Cloud Run (compare with the local baseline); `deletion_policy = "ABANDON"` on `google_sql_user.app` before any teardown.
4. 🟡 **Langfuse follow-ups** (`PENDING.md` §2): custom model prices (Groq models, `gemini-embedding-001`), Langfuse keys in Secret Manager for Cloud Run, verdict scores.
5. 🟡 **Promptfoo follow-ups** (`PENDING.md` §2): full-cascade eval, CI gate, the empty GPT-OSS reply.
6. 🟡 **Public API abuse protection** (user decides): suggested a `slowapi` per-IP limit + `claim_text` `max_length` before the next public demo; a per-user limit with the login and Phase 1.E.
7. 🟢 **Reliability backlog** in `PENDING.md` §4: MCP server replicas, the dead-letter queue, not retrying 4xx responses, and a stepped ingestion load test.
8. ⚪ Then Phase 1.F (dynamic provider selection), 1.G (High-Value Court), 2 (confidence layer), 3 (drift detection), and AWS (Phase 6 secondary).

## Environment state
- **Infrastructure reference:** `docs/infrastructure/gcp_infrastructure.md` (what runs where, service accounts, secrets, exposure, operating commands, cost). Update it with any `infra/` change.
- **GCP project `project-e0ad10c9-0b2f-4dc0-ac6`:** free-trial credit, billing enabled, $20 budget alert. Container Scanning is **not** enabled (it's paid). **Billing while the demo is up:** Cloud SQL (~$8/month) plus the two worker pools (rough estimate ~$50/month each, not verified).
- **Tools:** Terraform v1.16.2, google provider v8.4.0 and random provider v3.9.1 (pinned in `infra/.terraform.lock.hcl`).
- **Local stack:** `.env` is on `LLM_PROVIDER=mock`. For real Vertex: `docker compose -f docker-compose.yml -f docker-compose.gcp.yml up -d` with `LLM_PROVIDER=vertex`. For load or chaos tests: `docker-compose.chaos.yml` (mocks).
- **Cloud-session stack (new):** `.claude/hooks/session-start-env.sh` gives every cloud session a working `pytest`/`ruff`/`mypy` against real PostgreSQL 16 + pgvector and RabbitMQ, no Docker. `LLM_PROVIDER=mock` there too — no API keys are in that container.
- The dev DB holds test rows (prefixes `chaos-`, `tput-`, `prof-`, `vertex-e2e-`).

## Gotchas that still apply
- A `terraform plan`/`apply` that sits silently for minutes is the Cloud Billing API returning `429`; the provider retries without printing. Wait a minute and re-run. If it was killed, release the leftover lock: `terraform force-unlock -force <generation>`.
- Every plan must pass `-var demo_up=false` while the demo is down: the default is `true`.
- Dependencies aren't pinned except where noted. SQLAlchemy is capped `<2.1` (2.1.0 dropped `greenlet` by default).
- Inside containers, `VERTEX_PROJECT` must be set explicitly. A Vertex auth failure shows up as judges failing closed to `REJECT`, not as an auth error.
- Gemini 3.x models return 404 on regional Vertex endpoints: chat must use `global`.
- After migrating the dev DB from the host, rebuild every image built from `worker.Dockerfile` (`worker`, `sweeper`, `migrate`) before `docker compose up`.
- The chaos test kills the worker by its fixed name (`agentic_worker`), so run it without `docker-compose.scale.yml`.
- Measure scaling with `docker pause`, not `stop`/`start`.
- `updated_at` uses `clock_timestamp()`, because the worker holds a transaction open.
- `infra/backend.tf` can't use variables (the backend loads first).
- Run `terraform` from `infra/`.
- Cloud Run job output goes to Cloud Logging, not the terminal.
- The MCP SDK's `host:*` allowlist pattern needs a port; Cloud Run's `Host` has none, so cloud hosts go into `MCP_ALLOWED_HOSTS` exactly.
- The first `/api/v1/system-health` after idle reports `"mcp": false` (cold start).
- Terraform compares Cloud Run `volumes`/`volume_mounts` in order.
- Cloud Run worker pool logs: filter on `resource.labels.worker_pool_name="worker"` (not `service_name`).
- The `!` prefix only works in the Claude Code prompt, not in a normal PowerShell window.
- Neither `.claude/settings.json` nor other harness hook config can be edited by Claude itself (self-modification guard) — the user makes that one edit by hand, in any session.
- **New (2026-09-25):** PostgreSQL/RabbitMQ do not persist between shell invocations inside a Claude Code on the web container — the `session-start-env.sh` hook must (and does) start them fresh every session.
- **New (2026-09-25):** a cloud session's designated branch can be deleted remotely once its PR merges; rebuild it from `origin/main` under the same name rather than assuming its history is still there.
