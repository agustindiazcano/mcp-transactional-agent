# LLMOps & Observability

How the quality of the system's LLM decisions is measured: what runs today, what comes next, and which tools were deliberately left out. The summary lives in the README's [LLM Evaluation & Observability](../../README.md#llm-evaluation--observability) section; this document has the detail.

> **Status:** the runtime checks and token-usage logging are implemented. Promptfoo and Langfuse are the next increment, and Ragas comes later. None of the three is a declared dependency yet. The work is tracked in `PENDING.md` Step 3.

## 1. Implemented today

- **Runtime decision check:** the Asymmetric Double LLM-as-a-Judge (Gemini and GPT-OSS 20B via Groq) evaluates every proposed action concurrently, and a Supreme Court judge breaks ties. The user's text reaches the judges fenced as untrusted data.
- **Pre-execution shield:** a Prompt Guard model (`llama-prompt-guard-2-22m`) scores each claim for jailbreak and injection attempts before any judge runs.
- **Cost accounting:** `src/agents/token_usage.py` logs a structured `llm_token_usage` line (stage, provider, input and output tokens) at every real LLM call site. The README's Cost per Transaction table was built from these lines.

These checks decide individual claims. What they don't give is a measure of how often they decide correctly. That is the gap the next two tools close.

## 2. Offline evaluation with Promptfoo (next)

A labeled set of about 100 claims, run against the judges' real prompts and models:

- **The cases:** legitimate claims, obvious fraud, borderline refunds (amount limits, missing data), and prompt-injection attempts, each labeled with the expected verdict.
- **What it reports:** precision and recall of APPROVE, false approvals (the costly error in a refund flow), and verdict stability across repeated runs of the same claim. Stability matters here because Gemini ignores `temperature=0`, so Judge 1 and the Supreme Court are not deterministic.
- **Red-teaming:** Promptfoo's prompt-injection red-team probes generate adversarial inputs beyond the hand-written ones.
- **In CI:** a change to a prompt or a model that drops accuracy below the agreed threshold fails the build. Each run makes real LLM calls, so it runs when prompts or models change (or on demand), with Promptfoo's cache, instead of on every push.

## 3. Tracing with Langfuse (next)

One trace per claim: the Prompt Guard, each judge, and the Supreme Court, each with its input, output, latency, tokens, and cost. It attaches to the existing LangChain chat models through a callback, so the orchestration code doesn't change. A failed or escalated claim then becomes one inspectable trace instead of log lines stitched together by `request_id`. The evaluation scores from Promptfoo can be attached to the same traces.

## 4. RAG evaluation with Ragas (later)

Ragas scores the retrieval → judge path: **context relevance** (is the retrieved policy chunk about the claim?) and **groundedness** (does the judge's verdict rely only on what was retrieved, not on invented policy?). It's deferred because the knowledge base holds 4 chunks of `docs/policies/refund_policy.md` today, too few for these scores to say much. It becomes worth running once the policy corpus grows.

## 5. Not adopted, and why

- **LangSmith:** it overlaps with Langfuse, and its strength is tracing LangChain chains and agents. Here the orchestration is custom code, and LangChain is only a provider-adapter layer, so LangSmith would add a second tracer without a second view. `LANGCHAIN_TRACING_V2` should stay unset.
- **TruLens:** it bundles tracing with the RAG triad (groundedness, context relevance, answer relevance). Langfuse and Ragas cover those two jobs separately, without a second dashboard.

Fewer tools, fully wired, beat several half-integrated ones.
