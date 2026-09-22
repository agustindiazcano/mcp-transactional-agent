# LLMOps & Observability Framework

This document outlines the Observability and Regression Testing (LLMOps) strategy for the portfolio.

> **Status: design, not yet implemented.** Neither TruLens nor promptfoo is a declared dependency, and nothing in `src/` imports them. What runs today is the runtime Double LLM-as-a-Judge plus structured token-usage logging (`src/agents/token_usage.py`). The work to implement this document is tracked in `PENDING.md` Step 3.

## 1. Tracing and Real-Time Observability with TruLens

The plan is to wrap the LLM calls and the asynchronous workers to provide comprehensive real-time observability. This allows us to:

- Register the Directed Acyclic Graph (DAG) for each execution.
- Monitor latency on a per-node basis.
- Track token consumption to manage costs and rate limits.
- Evaluate the RAG/Agent triad metrics statistically:
  - **Groundedness**: Ensures the model's responses are strictly derived from the retrieved context.
  - **Context Relevance**: Measures how well the retrieved context matches the user's query.
  - **Answer Relevance**: Evaluates how well the final generated answer resolves the original query.

This level of tracing guarantees that any degradation in model performance or retrieval accuracy is immediately visible.

## 2. Regression Testing and CI/CD with promptfoo

To ensure that iterative improvements do not introduce regressions, promptfoo is planned for a CI pipeline (none exists yet).

- **Batch Test Matrices**: We execute tests across comprehensive matrices to cover edge cases.
- **Pre-deployment Verification**: We define a testing environment to evaluate the Primary Agent and the Judge prompts against 100+ edge cases before every deployment.
- **Behavioral Stability**: This pipeline ensures that modifying a system prompt will not break previously established behaviors or safety guardrails.
