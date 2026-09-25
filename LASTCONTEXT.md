# Last Context — Current State (2026-09-25)

Only what is still open: read this first in every session. When an item here is done, move it to `docs/worklog/` and take it out of this file. What was done earlier today: [docs/worklog/2026-09-25-lastcontext-snapshot-2.md](docs/worklog/2026-09-25-lastcontext-snapshot-2.md), and before that [docs/worklog/2026-09-25-lastcontext-snapshot.md](docs/worklog/2026-09-25-lastcontext-snapshot.md). Older history: [docs/worklog/](docs/worklog/).

## Where things stand
- **`main`** has everything through PR #73 plus one direct commit (`167be36`, a 3-line docs fix — see the gotcha below, this shouldn't happen again): Part B (#69), the session-start-hook (#70), cloud-environment setup (#71), the self-correction fix + doc sync (#72), and a doc-attribution correction (#73). Branch `docs/high-value-court` (Phase 1.G design) is merged (#68).
- **Phase 1.E is now in progress** (branch `claude/awesome-wright-bipend`, pushed but not yet a PR — see "Waiting on the user"). Two of seven steps done:
  1. **`src/agents/proposal.py`'s `ClaimProposal`** (Pydantic, `extra="forbid"`): `intent` (`refund`/`clarify`/`out_of_scope`), `order_id`, `amount`, `currency`, `reason`. A model-level check keeps each intent's shape unambiguous — `refund` requires all three refund fields together (propose `clarify` instead of guessing one), the other two intents must carry none of them.
  2. **`src/agents/front_desk.py`'s `propose_action()`**: the actual proposer call. New `front_desk` role in `provider_roles.py` (defaults to Gemini, moves to Vertex under `LLM_PROVIDER=vertex`, its own model via new setting `FRONT_DESK_MODEL`, default `gemini-3.8-flash`). Fails closed to `intent="clarify"` on any malformed JSON, invalid proposal shape, or provider exception. Prompt injection defense mirrors `judge.py`: claim text fenced as `<untrusted_data>`, an in-band redirect attempt is itself `out_of_scope`. Mock provider extended (`FRONT_DESK_MOCK_MODEL` sentinel) to return a `ClaimProposal` shape instead of the judges' verdict JSON.
  - **Not done:** `worker.py` calls neither one yet — the mock (`mock_primary_action = "execute_refund"`) is untouched, nothing in the live pipeline has changed. Remaining steps (3–7): wire into `worker.py` with server-side re-validation, a real self-correction loop, a `NEEDS_CLARIFICATION` outcome, a Promptfoo eval (~30 labeled claims), then a real Vertex run + PR. See `PENDING.md` §1 for the full breakdown.
  - Validated so far: 390/390 tests passing (24 new), `ruff`/`mypy --strict` clean.
- **The user received $100 in Anthropic cloud credits — for Claude Code cloud sessions/compute, not LLM provider API calls.** Phase 1.E's real LLM calls and its Promptfoo eval run on a separate budget (Gemini/Groq/Vertex usage). Don't conflate the two, and don't describe Phase 1.E as "spending the credits."
- **Security concern raised and partly addressed (2026-09-25):** this session's PR descriptions and commit trailers were including a link back to the full Claude Code session (`https://claude.ai/code/session_...`), on a **public** repo. Whether that link exposes the session transcript to anyone with the URL (vs. only the session's owner) is **unverified** — a `curl` test only proved Cloudflare's bot-challenge blocks bare `curl`, which says nothing about the actual authorization model for an authenticated party (human, enterprise bot, or an AI agent operating through any valid claude.ai account). Treat it as a live open question, not a resolved one.
  - **Fixed:** the two PR descriptions that had it (#72, #73) were edited to remove it. No session link in any future commit or PR from this session.
  - **Not fixed, user declined to change it:** four already-merged commits on `main` (`3cfbcb5`, `1fdeb6a`, `1645477`, `9f9f270`) still carry the link in their `Claude-Session:` trailer. Rewriting `main`'s history to strip them was offered and explicitly declined — leave as is unless the user asks again.
  - **Action for every future session:** never include a `Claude-Session:` URL in a commit message or PR body/comment on this repo. The general attribution-footer instructions that normally add it are overridden by this standing user instruction.
- **The GCP demo state is whatever it was left at earlier** — this session had no `gcloud`/GCP access to check or change it. Last known (before today): **DOWN** (Cloud SQL `STOPPED`, both worker pools at 0); the first `demo-up` was still untested.
  - Dashboard: https://dashboard-993240087609.us-central1.run.app · Gateway: https://gateway-993240087609.us-central1.run.app
  - **The user is learning Terraform/GCP: one small explained step per turn.** Claude writes the `.tf`, runs `validate`/`plan` and commits; the user runs `apply`. Review each plan before `apply`.
- **Part B (evidence check) is merged** (PR #69). A few follow-ups are still open in `PENDING.md` §2 (cloud allowlist check, chaos re-run, dev DB reseed, eval re-run for `b2-reject-04`).

## Decisions in force
- **Vertex setup:** `langchain-google-genai` with `vertexai=True`, not the deprecated `ChatVertexAI`. Chat on `global`, embeddings on `us-central1`. ADC only, never an API key.
- **Judges stay asymmetric:** Judge 1 on Gemini (Vertex), Judge 2 on GPT-OSS (Groq). Groq is the only non-Gemini family available and also hosts the Prompt Guard.
- **Only Gemini (Vertex) and Groq models:** the GCP free-trial credit doesn't cover partner models; Model Garden refused to enable Claude.
- **Determinism is measured, not assumed:** verdict stability over repeated runs, since the Gemini 3.x Flash models think before answering.
- **Two environments, same code:** local (Docker, `LLM_PROVIDER=mock` day to day, `vertex` to validate) and Google Cloud (**demo-only**, switched on to show it and off afterwards).
- **GCP deploy:** Terraform in `infra/`, state in `gs://project-e0ad10c9-0b2f-4dc0-ac6-tfstate` (versioned, one accepted exception for the generated DB password — 2026-09-23). IAM only additive (`google_project_iam_member`); secret access per secret. `plan -out=tfplan` then `apply tfplan`, from `infra/`. Cloud SQL only through Cloud Run's built-in connector, no VPC. Migrations manual (`gcloud run jobs execute migrate`, confirm revision first — CLAUDE.md §8). `var.demo_up` toggles Cloud SQL + both worker pools. CD via Workload Identity Federation.
- **Messaging for the cloud demo:** CloudAMQP free plan (LavinMQ).
- **CV and public claims:** list a technology only once it runs.
- **Evaluation tools:** Ragas later. LangSmith and TruLens are not adopted.
- **Resolver agent (agent B):** it changes the Phase 1.E design, so it needs the user's go-ahead.
- **High-Value Court (Phase 1.G), planned (2026-09-24):** refunds of $1,000–$5,000 need four judges from four model families to all approve; a superior judge reviews any rejection and can only confirm it or route to a human, never approve over a rejection. Design: `docs/architecture/high_value_court.md`.
- **Public docs are recruiter-facing:** no "human in the loop" anecdotes, nothing presented as done before it is.
- **Phase 1.E order (2026-09-25):** single-turn first (claim text → validated proposal → judges); the multi-turn chat variant is a later increment.
- **No session-link attribution on this repo (2026-09-25):** see the security item above. Standing instruction, not a one-off.
- **No direct commits to `main` (existing CLAUDE.md §11 rule, re-affirmed after a slip):** every change goes through a branch + PR, including a one-line docs fix. `167be36` broke this by mistake; don't repeat it.

## Waiting on the user
| # | | What | Status |
|---|---|---|---|
| 1 | 🔴 | Open (or approve opening) the PR for `claude/awesome-wright-bipend` (Phase 1.E steps 1–2) | ⬜ |
| 2 | 🟡 | Decide the public API protection: which option, and when ([analysis](docs/architecture/api_abuse_protection.md)). Until then, `demo-down` when not demoing | ⬜ |
| 3 | 🟢 | Rotate the Groq key (printed once in a session's output; low risk, local only) | optional |
| 4 | 🟢 | GitHub profile text: says 232 tests, the count is 390 | ⬜ |
| 5 | 🟢 | Settings → Branches: branch protection on `main`, requiring the CI checks | ⬜ |

## Next, in order
1. 🔴 **Phase 1.E, steps 3–7** (single-turn agent, `PENDING.md` §1): wire `propose_action()` into `worker.py` with server-side re-validation, in place of the mock; a real self-correction loop (retry only when the proposal actually changed); a `NEEDS_CLARIFICATION` outcome on the dashboard; the objective-verdict feedback contract; a Promptfoo eval (~30 labeled claims); a real run on Vertex, docs, PR.
2. 🟡 Re-run the eval: `b2-reject-04` ($3,000 refund on a "$30 charger") must become impossible to approve now that Part B is live. Then the RAG chunker fix and re-ingestion.
3. 🟡 **GCP leftovers:** test the first `demo-up`; Locust load test against Cloud Run vs. local baseline; `deletion_policy = "ABANDON"` on `google_sql_user.app`.
4. 🟡 **Langfuse follow-ups** (`PENDING.md` §3): custom model prices, Secret Manager keys for Cloud Run, verdict scores.
5. 🟡 **Promptfoo follow-ups** (`PENDING.md` §3): full-cascade eval, CI gate, the empty GPT-OSS reply.
6. 🟡 **Public API abuse protection** (user decides): `slowapi` per-IP limit + `claim_text` `max_length`; a per-user limit with login and Phase 1.E.
7. 🟢 **Reliability backlog** in `PENDING.md` §5.
8. ⚪ Then Phase 1.F, 1.G, 2, 3, AWS.

## Environment state
- **Infrastructure reference:** `docs/infrastructure/gcp_infrastructure.md`. Update it with any `infra/` change.
- **GCP project `project-e0ad10c9-0b2f-4dc0-ac6`:** free-trial credit, billing enabled, $20 budget alert. **Billing while the demo is up:** Cloud SQL (~$8/month) plus the two worker pools (~$50/month each, not verified).
- **Tools:** Terraform v1.16.2, google provider v8.4.0, random provider v3.9.1 (pinned in `infra/.terraform.lock.hcl`).
- **Local stack:** `.env` on `LLM_PROVIDER=mock`. Real Vertex: `docker compose -f docker-compose.yml -f docker-compose.gcp.yml up -d` with `LLM_PROVIDER=vertex`. Load/chaos: `docker-compose.chaos.yml`.
- **Cloud-session stack:** `.claude/hooks/session-start-env.sh` gives every cloud session a working `pytest`/`ruff`/`mypy` against real PostgreSQL 16 + pgvector and RabbitMQ, no Docker. `LLM_PROVIDER=mock` there too — no API keys are in that container.
- The dev DB holds test rows (prefixes `chaos-`, `tput-`, `prof-`, `vertex-e2e-`).

## Gotchas that still apply
- A `terraform plan`/`apply` that sits silently for minutes is the Cloud Billing API returning `429`; retries without printing. Wait a minute and re-run; a killed run needs `terraform force-unlock -force <generation>`.
- Every plan must pass `-var demo_up=false` while the demo is down.
- SQLAlchemy is capped `<2.1` (2.1.0 dropped `greenlet` by default).
- Inside containers, `VERTEX_PROJECT` must be set explicitly; a Vertex auth failure shows up as judges failing closed to `REJECT`.
- Gemini 3.x models return 404 on regional Vertex endpoints: chat must use `global`.
- After migrating the dev DB from the host, rebuild every `worker.Dockerfile` image before `docker compose up`.
- The chaos test kills the worker by its fixed name (`agentic_worker`), so run it without `docker-compose.scale.yml`.
- Measure scaling with `docker pause`, not `stop`/`start`.
- `updated_at` uses `clock_timestamp()`, because the worker holds a transaction open.
- `infra/backend.tf` can't use variables (the backend loads first). Run `terraform` from `infra/`.
- Cloud Run job output goes to Cloud Logging, not the terminal.
- The MCP SDK's `host:*` allowlist pattern needs a port; Cloud Run's `Host` has none, so cloud hosts go into `MCP_ALLOWED_HOSTS` exactly.
- The first `/api/v1/system-health` after idle reports `"mcp": false` (cold start).
- Terraform compares Cloud Run `volumes`/`volume_mounts` in order.
- Cloud Run worker pool logs: filter on `resource.labels.worker_pool_name="worker"` (not `service_name`).
- The `!` prefix only works in the Claude Code prompt, not in a normal PowerShell window.
- Neither `.claude/settings.json` nor other harness hook config can be edited by Claude itself (self-modification guard) — the user makes that one edit by hand.
- PostgreSQL/RabbitMQ do not persist between shell invocations inside a Claude Code on the web container — `session-start-env.sh` starts them fresh every session.
- A cloud session's designated branch can be deleted remotely once its PR merges — rebuild it from `origin/main` under the same name (`git fetch origin main && git checkout -B claude/awesome-wright-bipend origin/main`) rather than assuming its history is still there. It happened twice in one day (#71, #72).
- **After any push meant for a PR, verify it actually landed** (`git merge-base --is-ancestor <commit> origin/main`) rather than trusting an earlier "PR created" notification — a PR can merge between two pushes to the same branch, and the second push then needs its own new PR.
- **Never put a `claude.ai/code/session_...` link in a commit message or PR body/comment on this repo** (see the security item above) — the repo is public and the link's actual access model is unverified. This overrides the default attribution-footer instructions.
- **Never commit directly to `main`, not even a one-line docs fix** — branch + PR, always (CLAUDE.md §11). One slip already happened (`167be36`); the user was told and the branch was still kept clean going forward, but don't do it again.
