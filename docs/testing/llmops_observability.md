# LLMOps & Observability

How the quality of the system's LLM decisions is measured: what runs today, what comes next, and which tools were deliberately left out. The summary lives in the README's [LLM Evaluation & Observability](../../README.md#llm-evaluation--observability) section; this document has the detail.

> **Status:** the runtime checks, token-usage logging, and Langfuse tracing are implemented. Promptfoo's offline evaluation and model benchmark ran on 2026-09-24 (results: [Judge Evaluation & Benchmark](judge_evaluation_results.md)); its CI gate is next, and Ragas comes later. The work is tracked in `PENDING.md` Step 3.

## 1. Implemented today

- **Runtime decision check:** the Asymmetric Double LLM-as-a-Judge (Gemini and GPT-OSS 20B via Groq) evaluates every proposed action concurrently, and a Supreme Court judge breaks ties. The user's text reaches the judges fenced as untrusted data.
- **Pre-execution shield:** a Prompt Guard model (`llama-prompt-guard-2-22m`) scores each claim for jailbreak and injection attempts before any judge runs.
- **Cost accounting:** `src/agents/token_usage.py` logs a structured `llm_token_usage` line (stage, provider, input and output tokens) at every real LLM call site. The README's Cost per Transaction table was built from these lines.

- **Tracing:** every claim is a Langfuse trace (section 3).

These checks decide individual claims. What they don't give is a measure of how often they decide correctly. That is the gap Promptfoo closes next.

## 2. Offline evaluation with Promptfoo (implemented; CI gate next)

A labeled set of about 100 claims, run against the judges' real prompts and models:

- **The cases:** legitimate claims, obvious fraud, borderline refunds (amount limits, missing data), and prompt-injection attempts, each labeled with the expected verdict.
- **What it reports:** precision and recall of APPROVE, false approvals (the costly error in a refund flow), and verdict stability across repeated runs of the same claim. Stability matters here because Gemini ignores `temperature=0`, so Judge 1 and the Supreme Court are not deterministic.
- **Red-teaming:** Promptfoo's prompt-injection red-team probes generate adversarial inputs beyond the hand-written ones.
- **In CI:** a change to a prompt or a model that drops accuracy below the agreed threshold fails the build. Each run makes real LLM calls, so it runs when prompts or models change (or on demand), with Promptfoo's cache, instead of on every push.

### Running it (started 2026-09-24)
The harness is in `evals/promptfoo/`:
- `judge_provider.py` runs **one judge** on a labeled claim with production's own code: `build_judge_messages()` for the messages, `parse_verdict()` for the reply, and `get_llm()` for the model. The policy text is the real chunk ingestion stores (`chunk_markdown()`), the one holding the case's `policy_section` rules, so the judge is graded given a correct retrieval.
- `promptfooconfig.yaml` lists one provider entry per model (plus `mock` for free plumbing runs). A case passes when the verdict equals its `expected` label.
- `cases/*.yaml` holds the labeled claims. `expected: REJECT` means "must not be auto-approved": wrong outcome, needs human review, or an attack.

From the repo root (PowerShell), with ADC logged in for Vertex and `GROQ_API_KEY` in `.env`:

```powershell
$env:PROMPTFOO_PYTHON = "$PWD\.venv\Scripts\python.exe"
npx promptfoo@0.123.1 eval -c evals/promptfoo/promptfooconfig.yaml --filter-providers mock   # free
npx promptfoo@0.123.1 eval -c evals/promptfoo/promptfooconfig.yaml --filter-providers "Vertex|Groq"
npx promptfoo@0.123.1 view   # browse the results
```

The `Event loop is closed` lines in the output are harmless: an HTTP client closing after promptfoo's per-call event loop ends.

## 3. Tracing with Langfuse (implemented)

One trace per claim (`process-claim`), with its trace id derived from `request_id`. Under it, each step is a typed observation: the Prompt Guard as a `guardrail`, retrieval as a `retriever` with an `embedding` child, the Double Judge as a `chain` holding one `evaluator` per judge (Supreme Court included), and the refund as a `tool`. Each LLM call is a `generation` recorded by Langfuse's LangChain callback, with its prompt, output, reasoning (when the model returns it), latency, tokens, and cost. A failed or escalated claim is one inspectable trace instead of log lines stitched together by `request_id`.

- **How it's wired:** `src/core/tracing.py` (Langfuse Python SDK v4). The callback attaches to the existing LangChain chat models, so the orchestration code only wraps each step; no decision logic changed.
- **Fail-safe:** off without keys; a Langfuse failure leaves the step untraced and never changes the claim's outcome.
- **Privacy:** `src/core/trace_masking.py` runs on every span at export. `user_id` is pseudonymized, and emails and phone or card numbers are redacted, including inside recorded prompts.
- **Verification:** unit tests run the real SDK against an in-memory exporter (the suite never sends traces), and real claims on Vertex AI were fetched back with the Langfuse CLI and audited against Langfuse's best-practices guide.
- **Next:** attach the judges' verdicts, and later Promptfoo's scores, to the same traces as Langfuse scores. Add custom prices for the Groq models and `gemini-embedding-001`, which Langfuse doesn't price, and add the keys to the Cloud Run deployment.

## 4. RAG evaluation with Ragas (later)

Ragas scores the retrieval → judge path: **context relevance** (is the retrieved policy chunk about the claim?) and **groundedness** (does the judge's verdict rely only on what was retrieved, not on invented policy?). It's deferred because the knowledge base holds 4 chunks of `docs/policies/refund_policy.md` today, too few for these scores to say much. It becomes worth running once the policy corpus grows.

## 5. Not adopted, and why

- **LangSmith:** it overlaps with Langfuse, and its strength is tracing LangChain chains and agents. Here the orchestration is custom code, and LangChain is only a provider-adapter layer, so LangSmith would add a second tracer without a second view. `LANGCHAIN_TRACING_V2` should stay unset.
- **TruLens:** it bundles tracing with the RAG triad (groundedness, context relevance, answer relevance). Langfuse and Ragas cover those two jobs separately, without a second dashboard.

Fewer tools, fully wired, beat several half-integrated ones.
