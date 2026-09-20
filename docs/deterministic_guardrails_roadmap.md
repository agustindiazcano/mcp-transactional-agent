# Research & Differentiation Roadmap
### Deterministic, Auditable, and Formally-Grounded Mechanisms Beyond LLM-as-Judge

**Author:** Agustin Diaz-Cano
**Context:** Companion document to the Agentic MCP Engine and RAG Gateway project, and the Volumetric Logic (VL) formalism. Tracks techniques explored, validated, in progress, or planned, and explains what each one is *for* in this specific system — not as a generic technique catalog, but as a rationale log for architectural decisions.

**Core thesis of this roadmap:** most LLM-engineering roles and interviews test for prompt orchestration and RAG plumbing, and treat "LLM-as-Judge" as the ceiling of rigor for validating agent behavior. This document tracks a different bet: identify which decisions in an agentic system can be made deterministic, auditable, and formally grounded, and reserve the LLM's probabilistic judgment only for what genuinely requires it. Each entry below states honestly whether it helped, by how much, and why — negative and inconclusive results are kept, not filtered out.

---

## Part 1 — Implemented and Benchmarked (real code, real numbers)

### 1.1 Classical ML rigor as a baseline discipline
**What it is:** proper train/test methodology, threshold selection via precision-recall curves (not a fixed τ=0.5), ROC-AUC vs. PR-AUC selection depending on class imbalance, mandatory comparison against a trivial baseline (`DummyClassifier`), and root-cause diagnosis when a method underperforms instead of hiding the result.

**Why it matters here:** most LLM-focused engineers today never benchmarked anything against Logistic Regression or an RBF-SVM with correct methodology — they only know black-box `.fit()`/`.predict()` calls. Demonstrating this discipline is a stronger signal of research maturity than any single "advanced" algorithm, because it shows the process is trustworthy, not just the headline number.

**Status:** ✅ Done. `vl_anti_fraud_benchmark_v3.py`, `vl_anti_fraud_benchmark_v4.py`, `vl_routing_benchmark.py`.

**Result:** Logistic Regression and RBF-SVM outperformed VL on raw accuracy in both the fraud-detection benchmark (ROC-AUC 0.93–0.95 vs. VL's 0.80–0.82) and, much more severely, in the multi-class routing benchmark (risk ≈ 0.39 vs. ≈ 0.01–0.02 at comparable coverage). Both results are kept and documented with root-cause diagnosis, not discarded.

---

### 1.1b Logistic Regression & RBF-SVM as competitive baselines
**What they are:** the two classical, decades-old supervised classifiers used throughout this roadmap as the benchmark to beat. Logistic Regression fits a smooth probabilistic decision surface by jointly optimizing all classes together; RBF-SVM finds a maximum-margin boundary using Gaussian kernels (VL's own related-work section already places itself in the same lineage — compact-support cones vs. Gaussian kernels, max-aggregation vs. margin optimization).

**Why they matter here:** these are not a footnote — they are the actual winners of both benchmarks run so far, and by a wide margin in the multi-class case. Their advantage is structural, not incidental: both are *discriminative* models that optimize a decision boundary using all classes at once, which is exactly the property VL's independent per-class predicates lacked (see 1.5's root-cause diagnosis). Being able to explain precisely *why* a 1958-era method (logistic regression) and an 1990s method (RBF-SVM/kernel methods) beat a novel formalism — rather than just reporting the loss — is the actual differentiating skill here, not the exotic algorithm.

**Status:** ✅ Done. Implemented as baselines in `vl_anti_fraud_benchmark_v3.py`, `vl_anti_fraud_benchmark_v4.py`, `vl_routing_benchmark.py`, with proper threshold calibration (see 1.1) rather than default settings — a sloppier baseline would have understated how far ahead they actually are.

**Result:** Logistic Regression — ROC-AUC 0.9254 / PR-AUC 0.7168 / F1 0.6887 (fraud); near-zero risk at 80-95% coverage (routing). RBF-SVM — ROC-AUC 0.9528 / PR-AUC 0.7386 / F1 0.7626 (fraud), fastest-at-scale in routing but ~16x slower than VL in the fraud benchmark's batch latency. Both results are the empirical anchor the rest of this roadmap is calibrated against.

---

### 1.2 Volumetric Logic (VL) — geometric, interpretable decision layer
**What it is:** a formalism of my own authorship: finite unions of weighted closed balls in ℝⁿ, with a normalized radial proximity function and max-aggregation, provably equivalent to a zero-order Takagi-Sugeno fuzzy inference system, with Lipschitz approximation guarantees (McShane-type envelope construction) and O(kn) evaluation complexity.

**Why it matters here:** it's a fully auditable, zero-training alternative to a black-box classifier for high-stakes decision points (`execute_refund`, `validate_fraud_score`). Every decision traces back to "which known prototype did this match, and by how much" — something no MLP or LLM-Judge can give exactly.

**Status:** 🟡 Working paper (v0.1), reference implementation exists, first empirical benchmarks run.

**Result (binary fraud detection, with AND-NOT composition per the paper's own lattice theorem):** modest but real improvement over single-predicate VL (PR-AUC +20% relative), still below LR/SVM on raw accuracy. Best positioning found: not a classifier replacement, but a near-zero-latency first-line filter in a **cascade architecture** (see 1.4).

---

### 1.3 Classification with a Reject Option (Chow's Rule, 1970)
**What it is:** a classic, 50+ year old formalization of letting a classifier abstain ("escalate") instead of forcing a decision when confidence is low, measured via the **risk-coverage curve** (accuracy on accepted cases vs. % of cases resolved without escalation).

**Why it matters here:** almost no one in current LLM engineering names this literature, even though "should I trust this output or send it to a human/bigger model" is exactly this problem. Framing VL's threshold τ this way — instead of an ad hoc cutoff — ties the engineering decision to established theory.

**Status:** ✅ Implemented and benchmarked. `vl_routing_benchmark.py`.

**Result:** used as the evaluation framework for the routing experiment (see 1.5); revealed VL's structural weakness in the multi-class case rather than papering over it.

---

### 1.4 Cascade Architectures (cheap deterministic filter → expensive model)
**What it is:** route the majority of "easy" cases through a fast, cheap, deterministic mechanism, and escalate only ambiguous cases to a more expensive, more accurate model (classical precedent: Viola-Jones cascade classifiers in computer vision; modern precedent: small-model-routes-to-large-model patterns in production LLM systems).

**Why it matters here:** this is the actual honest positioning for VL after benchmarking — not "VL beats SVM," but "VL resolves the confident majority of cases in ~1-2 microseconds, RBF-SVM was ~16x slower in the fraud benchmark, and only the ambiguous minority needs to pay for the expensive path."

**Status:** 🟡 Positioning validated by the latency numbers already collected; not yet implemented as an explicit two-stage pipeline in the MCP worker.

---

### 1.5 Semantic Routing / Mixture-of-Experts-style Dispatch
**What it is:** using geometric proximity to known prototype clusters to decide which model/agent/tool should handle an incoming request, instead of an LLM call or a trained (opaque) gating network. Directly related to MoE gating (Shazeer et al., 2017) and to commercial LLM-routing products (RouteLLM, semantic-router).

**Why it matters here:** this is a live, funded infrastructure problem in the industry right now (cost/latency optimization by routing cheap vs. expensive models), not an academic curiosity.

**Status:** ✅ Implemented and benchmarked — **and it failed**, honestly and instructively. `vl_routing_benchmark.py`.

**Result:** naive multi-class VL (independent per-class predicates + argmax) underperformed badly (risk ≈ 0.39 vs. ≈ 0.01–0.02 for LR/SVM at matched coverage). Root cause identified: per-class predicates are calibrated independently, so their truth values are not on a comparable scale — argmax across uncalibrated fuzzy memberships does not yield a sound decision boundary, unlike a jointly-optimized softmax.

**Proposed fixes (not yet implemented):**
- Post-hoc calibration per predicate (Platt scaling / isotonic regression) before comparing across classes.
- Pairwise AND-NOT composition (class_i AND NOT union(rest)) extending the pattern that *did* work in the binary fraud case.
- Per-predicate score normalization (z-score against its own training distribution) before cross-class comparison.

---

## Part 2 — In Progress / Partially Implemented (per project README)

### 2.1 LLM-as-a-Judge + Belief Rule Base (fuzzy scoring + expert system)
**What it is:** a second, deterministic guardrail alongside the LLM-Judge — fuzzy-scored retrieval signals feeding a rule base with explicit belief degrees, applied to the highest-risk tools.

**Why it matters here:** this is the project's Phase 2, and VL is a formally stronger candidate to implement it than a generic fuzzy layer, because VL comes with proven lattice-composition and approximation properties instead of ad hoc membership functions.

**Status:** 🟡 In progress (per README). VL benchmarks in Part 1 are the empirical validation work for this phase.

---

### 2.2 Kalman-Filtered Quality Drift Detection
**What it is:** treating per-request LLM-Judge / RAG-Triad scores as a noisy time series, using a Kalman filter to estimate the "true" quality state and alert only on sustained drift, not single-batch noise.

**Why it matters here:** complements VL/K-Means-based anomaly detection — Kalman catches *slow drift over time*, whereas a geometric proximity check catches *type-of-input anomalies at a single point in time* that Kalman's smoothing would miss.

**Status:** 🔵 Experimental / roadmap (per README). Not started.

---

## Part 3 — To Explore (identified, not yet implemented)

### 3.1 Conformal Prediction
**What it is:** a distribution-free framework for producing prediction sets with a formally guaranteed error rate (e.g., "the correct answer is in this set with 95% statistical guarantee," not an informal confidence score).

**Why it matters here:** already named in the project's own `advanced_ai_roadmap.md`. Almost no LLM engineering role or interview narrative mentions this, despite it being one of the most rigorous tools available for quantifying LLM output uncertainty with an actual mathematical guarantee instead of a heuristic score.

**Status:** 🔵 Not started. Highest-value next addition for signaling research depth.

---

### 3.2 FSM-Constrained Decoding
**What it is:** masking invalid tokens at generation time via a finite state machine, so the LLM's output is valid *by construction* (e.g., guaranteed valid JSON, or a tool call matching an exact schema) instead of hoping the model complies and validating after the fact.

**Why it matters here:** directly relevant to the MCP tool-calling path — a deterministic guarantee on output structure, upstream of any LLM-Judge check.

**Status:** 🔵 Not started (in project roadmap).

---

### 3.3 Rule-Based Reward Models (deterministic DPO/RLHF alignment)
**What it is:** using code evaluators or deterministic checkers as the reward signal for preference optimization, instead of a trained (and therefore itself probabilistic and gameable) reward model.

**Why it matters here:** same underlying philosophy as the whole project — replace a learned proxy with a verifiable mechanism wherever the domain allows it.

**Status:** 🔵 Not started (in project roadmap).

---

### 3.4 Shielded / Safe Reinforcement Learning
**What it is:** formal framework (Alshiekh et al., 2018) for wrapping a learned policy with a deterministic "shield" that enforces known hard safety constraints, so the learned component only has to handle what genuinely requires generalization.

**Why it matters here:** this is the exact formalization of the "walls are lava, hardcode that, let the agent learn the other 10%" principle already applied informally in the maze-navigation robot experiment. Naming it properly connects that project to established literature.

**Status:** 🔵 Not started as a formal write-up; already applied informally in a separate robotics experiment (arithmetic / two-moons / quadruped locomotion with VL) — undocumented, code-only.

---

### 3.5 Artificial Potential Fields (Khatib, 1986)
**What it is:** classical robotics navigation technique — obstacles generate repulsive fields, goals generate attractive fields, and the agent follows the resulting gradient.

**Why it matters here:** direct structural relative of VL (radial functions, geometric composition) applied to a different domain (navigation/control instead of classification). Relevant if the maze/quadruped experiments are ever written up.

**Status:** 🔵 Not started as an explicit comparison; noted as related work only.

---

## Summary Table

| # | Technique | Status | Result so far |
|---|---|---|---|
| 1.1 | Classical ML benchmarking rigor | ✅ Done | Validated the whole roadmap; found VL loses on raw accuracy, twice |
| 1.1b | Logistic Regression & RBF-SVM | ✅ Done | Won both benchmarks; root cause of the win identified, not just reported |
| 1.2 | Volumetric Logic (VL) | 🟡 Working paper | Competitive-ish in binary case, weak alone in multi-class |
| 1.3 | Reject Option (Chow's Rule) | ✅ Done | Used as the evaluation framework for routing |
| 1.4 | Cascade architecture | 🟡 Positioning validated | Latency case is strong; not yet wired into the MCP worker |
| 1.5 | Semantic Routing / MoE-style dispatch | ✅ Done — failed instructively | Root cause found: uncalibrated cross-predicate scores |
| 2.1 | LLM-Judge + Belief Rule Base | 🟡 In progress | VL benchmarks are its empirical grounding |
| 2.2 | Kalman drift detection | 🔵 Roadmap | Not started |
| 3.1 | Conformal Prediction | 🔵 Roadmap | Not started — highest-value next step |
| 3.2 | FSM-Constrained Decoding | 🔵 Roadmap | Not started |
| 3.3 | Rule-Based Reward Models | 🔵 Roadmap | Not started |
| 3.4 | Shielded / Safe RL | 🔵 Roadmap | Applied informally elsewhere, undocumented |
| 3.5 | Artificial Potential Fields | 🔵 Roadmap | Related work only |

---

*This document is meant to be updated as experiments run — entries move from Part 3 to Part 1 only when there is actual code and an actual number attached, negative results included.*