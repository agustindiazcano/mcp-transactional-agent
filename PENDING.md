# 📝 Roadmap: Agentic MCP Engine

Personal working notes. See README.md's Roadmap table and Phase sections for the canonical, detailed version of all of this — this file is the short, checklist-style view.

## Phase 1.B: Perimeter Hardening (Zero-Trust MCP)
- [ ] **Server-side authentication:** middleware on the MCP port (8080) that rejects every request without a valid cryptographic Bearer Token.
- [ ] **Strict validation (Pydantic):** hard business limits on tool arguments — e.g. reject refunds above `REFUND_MAX_AMOUNT` at the interface, no matter what the LLM asks for.
- [ ] **Rate limiting:** per-endpoint request quota, against fund-draining and DoS.

## Phase 1.C: Load Validation (the one open item in this phase)
- [ ] **Concurrency simulation:** 100+ concurrent requests (simulated claimants) against the *containerized* stack (not bare `localhost`) to stress the Gateway and queue — `tests/performance/locustfile.py` already exists and runs locally; this is about re-running it against `docker compose` and at scale.
- [ ] **Concurrency validation:** confirm the pessimistic locks (`SELECT ... FOR UPDATE`) hold without deadlocks under that load.
- [ ] **Metrics:** publish throughput (req/s) and P95 latency into the README's `Cost per Transaction` / `System Performance & Telemetry` tables, replacing the placeholder values.

## Phase 6: Cloud Migration (AWS Serverless)
> Goal: ~$5/month, or $0 on free tier.
- [ ] **IAM and Bedrock:** least-privilege IAM policies to consume the foundation models. Add VPC endpoints (PrivateLink) so traffic doesn't leave AWS.
- [ ] **Embeddings provider swap:** migrate Phase 1.D's embeddings pipeline from Gemini/OpenAI to Amazon Titan Embeddings via Bedrock — this is where Bedrock enters the RAG pipeline, deliberately not in Phase 1.D.
- [ ] **Serverless topology:** FastAPI → API Gateway, RabbitMQ → SQS, Worker → Lambda.
- [ ] **External database:** serverless PostgreSQL (Neon or Supabase) with pgvector, to keep that cost at $0.
- [ ] **Load re-test:** repeat Phase 1.C's load validation against the AWS deployment and compare metrics against local.

## Phase 4: Admin Ops Dashboard (Frontend)
> Requirement to validate the Full-Stack E-commerce profile.
- [ ] **Setup:** React + Vite project with TypeScript and TailwindCSS.
- [ ] **Real-time panel:** table consuming the API, showing transaction status (PENDING, PROCESSING, COMPLETED) via WebSocket, SSE, or polling.
- [ ] **Visual metrics:** throughput, latency, and approved-vs-rejected refund rate.

---

## Already done (not repeated above — see README.md for full detail)
- Phase 1 core engine: event-driven pipeline, MCP server, idempotency, Double Judge, Prompt Guard, self-correction loop, Supreme Court cascade judge, pessimistic locking + Recovery Sweeper.
- Phase 1.C, mostly: per-service Dockerfiles, full `docker-compose` orchestration (7 services), `docker compose up --build` deployment validation. Only load validation (above) remains open in this phase.
- **Phase 1.D, fully: RAG — common pattern, not tied to Bedrock.** `pgvector` extension + `knowledge_base` table (Alembic migration `7da4609fe11c`); `scripts/ingest_knowledge_base.py` chunks `docs/policies/refund_policy.md` and embeds it via Gemini `gemini-embedding-001` (truncated to 768 dims); the Worker runs a real cosine-similarity search (`embedding <=> claim_vector`, pgvector's `<=>` operator — not `<->`, which is L2/Euclidean distance, a mistake caught and fixed while implementing this) and injects the matched policy into the Double Judge's context, fail-open on any retrieval error. Validated end-to-end against the real Gemini API and a real Postgres. The Bedrock/Titan swap stays deferred to Phase 6.
- `mypy --strict` and the unit test suite are green.
