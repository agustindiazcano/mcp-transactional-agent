# High-Value Court (Phase 1.G)

**Status:** designed, not yet implemented (2026-09-24). Depends on Part B (deterministic evidence checks) shipping first.

A stricter review tier for refunds between **$1,000 and $5,000**: four judges from four different model families must all approve, and a superior judge on a stronger model reviews any rejection. It never overturns one.

---

## 1. Why

The [judge benchmark](../testing/judge_evaluation_results.md) showed three things that shape this design:

1. **A wrong approval's cost scales with the amount.** A false approval on a $3,000 refund costs 100× one on $30. Scrutiny should scale with it.
2. **Judges fail together when they share a model family.** All three Gemini models approved the same digital-goods claim that needed human review, and both Flash-Lite models approved a €4,800 claim against a $5,000 limit.
3. **Verdicts drift between runs.** Hours after the benchmark, both production judges approved that €4,800 claim 4 times out of 5. Two judges that happen to agree are not enough evidence for a large refund.

High-value claims are a small share of traffic, so a few extra LLM calls on them barely move the average cost per claim.

---

## 2. Design

### Routing
```
Deterministic checks (Part B) ── fail ──► PENDING_HUMAN_REVIEW
        │ pass
amount < $1,000             ──► standard pipeline (Judge 1 + Judge 2, Supreme Court on disagreement)
$1,000 ≤ amount ≤ $5,000    ──► High-Value Court
amount > $5,000             ──► PENDING_HUMAN_REVIEW (refund policy: over $5,000 needs manual review)
```

The amount is compared **after currency conversion to USD**, because the policy limit is in dollars. A €4,800 claim is over $5,000.

### The court
| Step | Rule |
|---|---|
| 1. Four judges, concurrently | Four judges from **four different model families**, same prompt (`build_judge_messages()`), each a REJECT on any error (fail-closed, as today) |
| 2. Unanimity | **All four APPROVE → approve.** Anything else goes to step 3 |
| 3. Superior judge | A stronger model (candidate: Gemini Pro on Vertex) reviews the claim together with the four verdicts and their reasons |
| 4. The superior judge can't approve | Its only outcomes are **confirm REJECT** or **route to human review**. It never turns a rejection into an approval |

### Why the superior judge can't approve
A tie-breaker that can approve over a "no" brings back exactly the risk the extra judges remove. The benchmark showed a tie-breaker repeating one judge's mistake. In this tier a single credible rejection is enough to stop an automatic payout. The superior judge's job is to separate two kinds of rejection:
- **Confirmed:** the claim really breaks the policy. It's rejected with an objective reason.
- **Uncertain:** the rejection looks shaky, or the judges disagree for reasons the policy doesn't settle. A human decides.

Either way, no money moves without all four judges agreeing.

### Why four families, not four judges
Adding judges only helps if their mistakes are independent. Two models from the same family tend to share blind spots (section 1), so the court counts **families**, not models. Today the project can use Gemini (Vertex) and the families hosted on Groq (GPT-OSS today; others, such as Llama or Qwen, to be confirmed on Groq and measured with the eval). Partner models on Vertex (Claude, Grok) would add families, but the GCP free-trial credit doesn't cover them.

---

## 3. Configuration

| Setting | Default | Meaning |
|---|---|---|
| `HIGH_VALUE_THRESHOLD_USD` | `1000` | Refunds at or above this amount (in USD) go to the court |
| `HIGH_VALUE_COURT_MODELS` | to be chosen with the eval | The four judges, one per model family |
| `SUPERIOR_JUDGE_MODEL` | to be chosen with the eval (candidate: Gemini Pro) | The superior judge |

The upper bound ($5,000) comes from the refund policy and `REFUND_MAX_AMOUNT`, not from a new setting.

---

## 4. What it costs and what it trades

| | Effect |
|---|---|
| Cost per high-value claim | 4 judge calls, plus 1 superior call when there's any rejection. At benchmark prices, a few tenths of a cent per claim |
| Latency | Judges run concurrently, so the court takes about as long as its slowest judge, plus the superior judge when called. The pipeline is asynchronous, so no user waits on it |
| False approvals | A wrong payout needs all four families wrong at once |
| False rejections | They go up: any one of four judges can stop a valid claim. For $1,000+ that's acceptable, since the claim goes to a human, not to a denial |

---

## 5. How it will be validated

The existing Promptfoo harness (`evals/promptfoo/`) grades it before it ships:
1. **Candidate models:** benchmark each candidate judge and the superior judge on the labeled set, as done for the current judges.
2. **The court as one provider:** grade the whole tier (four judges + superior judge) end to end, not each judge alone.
3. **High-value cases:** extend the dataset with claims between $1,000 and $5,000: legitimate ones, currency traps, amounts that contradict the claim, and attacks.
4. **Repeats spread over time**, not back to back, since verdicts drift between runs.

**Acceptance bar:** zero false approvals on the high-value cases across all repeats. The false-rejection rate is reported, not gated.

---

## 6. Dependencies and order

| # | Step | Why first |
|---|---|---|
| 1 | Part B: deterministic evidence checks (refund ≤ order amount, currency conversion, order owned by the user) | The benchmark's worst misses were arithmetic. Code catches them with certainty for every amount, before any judge |
| 2 | Currency conversion to USD | Needed for routing (section 2) and for the $5,000 limit |
| 3 | Pick the four families and the superior judge with the eval | Measured, not assumed |
| 4 | Build the court behind the routing, with the full-tier eval | Section 5 |

Related: [Judge Evaluation & Benchmark](../testing/judge_evaluation_results.md), [Phase 1.F](../../README.md#phase-1f--dynamic-llm-provider-selection-designed-not-yet-implemented) (per-role model selection, which this builds on).
