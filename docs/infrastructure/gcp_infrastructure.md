# Infrastructure: Local Stack and Google Cloud Deployment

**Status (2026-09-24):** the local Docker stack is complete. The Google Cloud deployment is at step 9 of 10: all services run on Cloud Run with real data in Cloud SQL, and real claims complete end to end. Step 10 (CD with GitHub Actions and a load test against Cloud Run) is not started. The Google Cloud environment is **demo-only**: it's switched on to show it and off afterwards.

This document describes what runs where, who can access what, and how to operate it. The design reasons behind each choice are in the README's [Phase 6](../../README.md#phase-6--cloud-deployment-google-cloud-primary-in-progress-and-aws-secondary) section and in `CLAUDE.md` §5f.

---

## 1. Two environments, same code

| | Local (development) | Google Cloud (demo) |
|---|---|---|
| Purpose | Day-to-day development and testing | Showing the system running in a managed cloud |
| Orchestration | `docker compose` (`docker-compose.yml`) | Terraform (`infra/`) + Cloud Run |
| Database | `pgvector/pgvector:pg16` container | Cloud SQL for PostgreSQL 16 + `pgvector` |
| Broker | `rabbitmq:3-management` container | CloudAMQP free plan (LavinMQ, AMQP 0-9-1) |
| LLMs | `LLM_PROVIDER=mock` by default; `vertex` to validate | `LLM_PROVIDER=vertex` (Judge 1, Supreme Court, embeddings) + Groq (Judge 2, Prompt Guard) |
| Secrets | `.env` file | Secret Manager, per-secret access |
| Vertex auth | The developer's ADC, mounted read-only into the worker (`docker-compose.gcp.yml`) | The Cloud Run service account |

The application code is the same in both. Only environment variables and connection strings change.

---

## 2. Local stack

`docker compose up --build` starts 8 services on the private `agentic_net` bridge network:

| Service | Image / Dockerfile | Port (host) | Role |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | Database with `pgvector` |
| `rabbitmq` | `rabbitmq:3-management` | 5672, 15672 (UI) | Broker |
| `migrate` | `docker/worker.Dockerfile` | — | One-shot `alembic upgrade head`; gates the app services |
| `mcp_server` | `docker/mcp_server.Dockerfile` | 8080 | MCP tools behind the Phase 1.B security boundary |
| `worker` | `docker/worker.Dockerfile` | — | Consumes claims, runs the guard, retrieval and judges, calls `execute_refund` |
| `sweeper` | `docker/worker.Dockerfile` | — | Recovery Sweeper: requeues claims abandoned by a crashed worker |
| `gateway` | `docker/gateway.Dockerfile` | 8000 | FastAPI: claim ingestion and read-only API |
| `dashboard` | `docker/dashboard.Dockerfile` | 8501 | Streamlit Ops Dashboard (reads only from the gateway) |

Override files:

| File | Use |
|---|---|
| `docker-compose.gcp.yml` | Real Vertex AI locally: mounts the host's ADC into the worker only |
| `docker-compose.chaos.yml` | Chaos and throughput tests: every LLM role on `mock`, MCP rate limit lifted, sweeper every 10 s |
| `docker-compose.scale.yml` | Removes the worker's fixed container name so `--scale worker=N` works |

Setup and day-to-day operations: [RUNBOOK.md](../../RUNBOOK.md).

---

## 3. Google Cloud: what runs where

Project `project-e0ad10c9-0b2f-4dc0-ac6`, region `us-central1`, on the free-trial credit with a $20 budget alert.

The path of one claim:

1. A client (or the dashboard) sends `POST /api/v1/claims` to the **gateway**, which publishes it to **CloudAMQP** and returns 202.
2. The **worker** pool consumes it and checks idempotency in **Cloud SQL**.
3. The worker runs the Prompt Guard (**Groq**), retrieves policy context (embedding on **Vertex AI**, similarity search in Cloud SQL), and runs the judges (Judge 1 and the Supreme Court on Vertex AI, Judge 2 on Groq).
4. On approval, the worker calls `execute_refund` on the **mcp-server** over HTTP/SSE with its bearer token. The MCP server writes the refund and its audit row to Cloud SQL.
5. The worker commits the final status. The **sweeper** pool requeues any claim a crashed worker left in `PROCESSING`.
6. The **dashboard** reads transactions only through the gateway's read-only API.

| Resource | Terraform | Type | Scaling | Notes |
|---|---|---|---|---|
| `gateway` | `cloudrun.tf` | Cloud Run service | 0–2 instances | Public, no auth yet (see [API Abuse Protection](../architecture/api_abuse_protection.md)) |
| `dashboard` | `cloudrun.tf` | Cloud Run service | 0–1, session affinity | Public; Streamlit keeps a websocket per browser session |
| `mcp-server` | `cloudrun.tf` | Cloud Run service | 0–1 | One instance: an SSE stream and its POSTs must reach the same one. Public at the Cloud Run layer; the Phase 1.B bearer token does the real authentication |
| `worker` | `cloudrun.tf` | Cloud Run worker pool | 1 (0 when the demo is down) | Pull-based consumer, no HTTP port |
| `sweeper` | `cloudrun.tf` | Cloud Run worker pool | 1 (0 when the demo is down) | Same image as the worker, different command |
| `migrate` | `migrate.tf` | Cloud Run job | one-shot | `alembic upgrade head` |
| `seed-orders` | `seed.tf` | Cloud Run job | one-shot | Loads the sample orders; skips existing ones |
| `ingest-knowledge-base` | `ingest.tf` | Cloud Run job | one-shot | Chunks and embeds the refund policy on Vertex; replaces the document's chunks on re-run |
| `agentic-pg` | `cloudsql.tf` | Cloud SQL, PostgreSQL 16 | `db-f1-micro`, zonal, 10 GB HDD, no backups | Database `agentic_engine`, user `app` |
| `app-images` | `main.tf` | Artifact Registry (Docker) | — | Images tagged with the commit they were built from, never `latest` |
| Secrets | `secrets.tf`, `secret_access.tf` | Secret Manager | — | See section 5 |
| State bucket | `backend.tf` | Cloud Storage (versioned) | — | Created by hand: Terraform can't create its own backend |

Service URLs follow Cloud Run's deterministic format `<service>-993240087609.us-central1.run.app`. Always use that form: it's the only host in the MCP server's `MCP_ALLOWED_HOSTS`.

---

## 4. Identity and access

One service account per workload, so each one's access is granted and revoked separately and the audit logs name the workload that acted. IAM is only ever added with `google_project_iam_member` (additive), never `_binding` or `_policy`, which would overwrite grants Terraform doesn't know about.

| Service account | Used by | Project roles | Secrets it can read |
|---|---|---|---|
| `worker-sa` | worker pool | `aiplatform.user`, `cloudsql.client` | `database-url`, `rabbitmq-url`, `groq-api-key`, `mcp-client-token` |
| `gateway-sa` | gateway | `cloudsql.client` | `database-url`, `rabbitmq-url` |
| `mcp-server-sa` | mcp-server | `cloudsql.client` | `database-url`, `mcp-clients-json` |
| `sweeper-sa` | sweeper pool | `cloudsql.client` | `database-url`, `rabbitmq-url` |
| `dashboard-sa` | dashboard | none | none |
| `migrate-sa` | `migrate` job | `cloudsql.client` | `database-url` |
| `seed-orders-sa` | `seed-orders` job | `cloudsql.client` | `database-url` |
| `ingest-kb-sa` | `ingest-knowledge-base` job | `aiplatform.user`, `cloudsql.client` | `database-url` |

`dashboard-sa` has no roles on purpose: without its own service account, Cloud Run would run the dashboard as the default Compute service account, which has Editor on the whole project.

---

## 5. Secrets

| Secret | Value set by | Read by |
|---|---|---|
| `database-url` | Terraform (built from the generated DB password and the Cloud SQL socket path) | every workload except the dashboard |
| `rabbitmq-url` | By hand (`gcloud`), imported into Terraform | worker, gateway, sweeper |
| `groq-api-key` | By hand | worker |
| `mcp-client-token` | By hand (a random token for the cloud client `worker-cloud`) | worker |
| `mcp-clients-json` | By hand (the MCP client registry: token hash + allowed tools), mounted as a file | mcp-server |

Rules:
- Terraform owns each secret's container and who can read it. Values Terraform doesn't generate are added by hand, never through Terraform variables, so they never enter the state.
- The one accepted exception: the Cloud SQL `app` password is generated by Terraform, so it and the `database-url` version live in the (private, versioned) state bucket.
- Access is granted per secret (`google_secret_manager_secret_iam_member`), never project-wide.
- The image's local-dev MCP client registry (whose token is public in `config.py`) is never used in the cloud: `MCP_CLIENTS_FILE` points at the mounted secret.

---

## 6. Network and exposure

| Path | How it's protected |
|---|---|
| Internet → gateway, dashboard | Public (`allUsers` invoker). TLS terminated by Cloud Run. No login and no rate limit yet: see [API Abuse Protection](../architecture/api_abuse_protection.md) |
| Internet → mcp-server | Public at the Cloud Run layer, because Cloud Run IAM would take the `Authorization` header the Phase 1.B token uses. Every call needs a valid bearer token, and only allowlisted hosts are accepted (`MCP_ALLOWED_HOSTS`) |
| Workloads → Cloud SQL | Cloud Run's built-in Cloud SQL connection: IAM-checked (`cloudsql.client`), mounted as a Unix socket under `/cloudsql/`. The instance has a public IP with no authorized networks and accepts encrypted connections only, so there's no other way in and no VPC is needed |
| Worker → Vertex AI | The worker's service account (`aiplatform.user`); no API key |
| Worker, gateway, sweeper → CloudAMQP | TLS AMQP URL from Secret Manager |

---

## 7. Operating it

All `terraform` commands run from `infra/` (from the repo root it finds no configuration).

| Task | Command | Notes |
|---|---|---|
| Preview a change | `terraform plan -out=tfplan` | A `tfplan` older than the last `.tf` edit is stale: re-plan |
| Apply a change | `terraform apply tfplan` | Review the plan first |
| Turn the demo off | `.\scripts\demo-down.ps1` | Stops Cloud SQL (data kept) and scales both worker pools to 0. Claims sent while down wait in CloudAMQP |
| Turn the demo on | `.\scripts\demo-up.ps1` | The first down → up cycle hasn't been tested yet |
| Check the DB revision | `gcloud run jobs execute migrate --region us-central1 --args=current --wait` | Confirm the current and target revision before any upgrade (CLAUDE.md §8) |
| Run migrations | `gcloud run jobs execute migrate --region us-central1 --wait` | Takes ~3 min to start (it pulls the worker image) |
| Reload demo data | `gcloud run jobs execute seed-orders ...` / `ingest-knowledge-base ...` | Both are safe to re-run |
| Read job logs | `gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=migrate" --freshness=10m --format="value(textPayload)"` | Job output goes to Cloud Logging, not the terminal |
| Read worker logs | filter on `resource.labels.worker_pool_name="worker"` | Not `service_name` |
| Push images | `docker push us-central1-docker.pkg.dev/project-e0ad10c9-0b2f-4dc0-ac6/app-images/<service>:<commit>` | Docker authenticates through the `gcloud` credential helper |

---

## 8. Cost

| Item | While the demo is up | While down |
|---|---|---|
| Cloud SQL `db-f1-micro` | ~$8/month | disk only |
| `worker` and `sweeper` pools (1 vCPU, 512 MiB each) | rough estimate ~$50/month each, not verified on the pricing page | $0 (0 instances) |
| gateway, dashboard, mcp-server | scale to zero; billed per request | $0 |
| Artifact Registry (~580 MB) | ~$0.01/month | same |
| CloudAMQP | free plan | free plan |
| LLM calls | ~$0.0004 per happy-path claim (AI Studio, 2026-09-21); Vertex cost pending the model benchmark | $0 |

The always-on worker pools are most of the cost, which is why the demo switch exists.

---

## 9. Not done yet

| # | | Item |
|---|---|---|
| 1 | 🟡 | CD: a merge to `main` deploys to Cloud Run through GitHub Actions and Workload Identity Federation (no keys in GitHub) |
| 2 | 🟡 | Reorder the Dockerfiles to install dependencies before `COPY src` (today every code change reruns the full `pip install`, 2–4 min per build) |
| 3 | 🟡 | Rate limiting and a login for the public gateway and dashboard ([API Abuse Protection](../architecture/api_abuse_protection.md)) |
| 4 | 🟢 | Locust load test against Cloud Run, compared with the local baseline (P95 87 ms) |
| 5 | 🟢 | Langfuse tracing on Cloud Run (keys into Secret Manager) |
| 6 | 🟢 | `deletion_policy = "ABANDON"` on `google_sql_user.app` before any teardown |
| 7 | ⚪ | Automatic secret rotation |
| 8 | ⚪ | AWS secondary target (README, Phase 6) |
