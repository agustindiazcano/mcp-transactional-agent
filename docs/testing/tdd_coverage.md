# TDD & Test Coverage Report

In this project, we strictly adhere to the **Test-Driven Development (TDD)** methodology through a *Red-Green-Refactor* cycle. All production code is written only after defining automated tests that must first fail.

This document explains in human-readable terms what we are testing and the current coverage of Phase 1 (Core Engine), divided into Unit Tests and Integration (End-to-End) Tests.

---

## 1. Unit Tests
These tests isolate individual components, mocking external dependencies (databases, networks) to test pure algorithmic logic. They run in milliseconds and require no infrastructure.

### A. Multi-Cloud Factory (`test_llm_factory.py`)
- **What do we test?** The Abstract Factory pattern responsible for instantiating the correct AI.
- **Coverage:**
  - Verify that the safe mode (Mock / `FakeListChatModel`) initializes correctly for local development.
  - Test that the factory initializes each supported provider (OpenAI, Gemini, Vertex AI, Groq, Bedrock) without errors when passed the appropriate parameters.
  - Ensure the system cleanly raises an error (`ValueError`) if an unknown provider is configured, preventing silent failures in production.

### B. LLM-as-a-Judge Guardrail (`test_judge.py`)
- **What do we test?** The deterministic interceptor that evaluates actions proposed by the agent before touching the database.
- **Coverage:**
  - **Approval:** We simulate a valid action proposal and ensure the judge strictly returns a JSON with `"verdict": "APPROVE"`.
  - **Rejection:** We simulate a policy violation or malformed arguments (e.g., an irrational refund amount) and guarantee the judge intercepts and returns `"verdict": "REJECT"`.

---

## 2. Integration and End-to-End Tests
These tests validate that the different components (API, Message Queue, Database, Worker, and MCP Server) communicate correctly with each other. They require real or connection-level mocked infrastructure.

### A. Database Domain (`test_database.py`)
- **What do we test?** The asynchronous persistence layer using PostgreSQL and SQLAlchemy.
- **Coverage:** We verify that asynchronous sessions can create and persist transactions, and subsequently read them correctly, ensuring the data model matches the Alembic migration.

### B. API Ingestion Gateway (`test_api.py`)
- **What do we test?** The public entry point (FastAPI).
- **Coverage:** We validate the high-concurrency flow. We simulate a client POST request, ensure Pydantic validates the schema, that the message is correctly serialized to RabbitMQ, and that the client immediately receives an HTTP `202 Accepted` without blocking to wait for processing.

### C. MCP Sandbox Server (`test_mcp_server.py`)
- **What do we test?** The standalone Model Context Protocol server.
- **Coverage:** 
  - Verify that the HTTP/SSE transport endpoint boots up and accepts connections.
  - Ensure critical tools (e.g., `execute_refund`, `get_user_history`) are correctly registered and published for the LLM to consume.

### D. Asynchronous Worker and Idempotency Engine (`test_worker.py`)
- **What do we test?** The heart of the transactional engine. This is the most complex test and covers the real E2E flow.
- **Coverage:**
  - **Idempotency (New Transaction):** A new message arrives, the worker verifies it doesn't exist in PostgreSQL, instantiates the LLM, simulates the Judge's evaluation, persists it as `COMPLETED`, and sends an `ACK` to RabbitMQ.
  - **Idempotency (Duplicate Transaction):** We fire a message at the worker with a `request_id` that already exists as `COMPLETED`. The worker must detect the duplicate, send an `ACK` to RabbitMQ to clear the queue, and **abort** execution without burning tokens or executing MCP tools twice.
  - **Rejection and Human Review:** We simulate the Judge rejecting the operation. We verify the worker does not change the status to completed, but strictly labels it as `PENDING_HUMAN_REVIEW` to prevent a financial disaster, sending an `ACK` so the message doesn't bounce infinitely in the queue.

---

This is the baseline certainty we operate with today. Every new feature or expert rule in **Phase 2** must first be covered by its respective test case before touching production code.
