# 001 — Gold Metrics: Three System-Level Signals for v1.0 Evaluation

**Status:** Proposed
**Date:** 2026-05-11

---

## Context

The v1.0 thesis is "improve by evidence, not intuition." That requires a measurement layer that exists *before* the components it scores, and a small set of metrics that produces a clear ordering between two pipeline variants on the same input.

The sprint plan's first cut listed six metrics (send rate, edit distance, session completion, cost, latency, classifier-vs-drafter attribution). Six is too many to act on. Half of them are component diagnostics dressed up as system metrics, and the rest overlap. This doc cuts the list to three and explains what got dropped and why.

**NOTE** All thresholds in this doc are bootstrapped placeholders. They get refit to data once the eval dataset reaches ~50 labeled examples (see Threshold Calibration under Send Rate). Treating the numbers as load-bearing before that point is a category error.

50 isn't a statistically motivated number — it's the point where I can fit thresholds against an LLM judge and surface the top failure modes, which is what I need at the calibration stage. It's not enough to make confident claims about whether v1.1 beat v1.0 on send rate; for that I'd want a few hundred examples and proper confidence intervals. The plan is to grow the set tiered — fifty for calibration, a couple hundred for regression gates in CI, and a larger set sampled from production once there's volume. Different sizes serve different jobs.

---

## What "gold" means here

A gold metric is:

1. **Implementation-independent.** A different team could rebuild Inbox0 with different components and the same metric would still apply.
2. **User-outcome facing.** It scores what the user experiences (was the email sent, how long did it take, how much did it cost to run), not how the system internally produced that experience.
3. **Cheap to capture.** Signal already lives in Slack actions, Gmail folder state, LangSmith traces, or a `time.perf_counter()` call. No new infrastructure required.


Component-level metrics (triage precision/recall, retrieval precision@K, cache hit rate, embedding quality) are diagnostics. They explain *why* a gold metric moved. They are not the metric. Component diagnostics live in their own brainstorms and ADRs.

---

## The Three Gold Metrics

### 1. Send rate

**Definition.** Of drafts produced and surfaced to the user in Slack, the fraction that result in a sent email matching the draft within a reasonable window (default: 24h).

**Grading rubric.** Send rate is binary at the metric level, but the grading rubric handles the Save-then-what cases:

| Slack action | Downstream outcome | Result |
|---|---|---|
| Approve | Email sent via GmailWriter | **Pass** |
| Save Draft | User sends draft as-is, or with edits below threshold | **Pass** |
| Save Draft | User sends draft with edits above threshold | **Fail** |
| Save Draft | User never sends, no manual reply | **Fail (attribution: triage)** |
| Save Draft | User never sends, but does send a manual reply | **Fail (attribution: drafter)** |
| Discard | User sends manual reply | **Fail (attribution: drafter)** |
| Discard | User sends nothing | **Fail (attribution: triage)** |

**Edit-distance threshold for "as-is vs heavily rewritten."** 

Single-metric edit checks are fragile, but without a real dataset of drafted-vs-sent pairs we're speculating about failure modes. The v1.0 design ships the minimum defensible composite and logs the rest as diagnostics for promotion-on-evidence.

*Shipping in v1.0 (as gates)*
- Token-level normalized Levenshtein. Edit cost in human-perceived units. Default pass: ≤ 0.20 of tokens changed.
- Semantic similarity. Full-text embedding cosine via `text-embedding-3-small`. Default pass: ≥ 0.92.


*Logged as diagnostic, promoted to gate on evidence:*

- **Content-word overlap (POS-filtered Jaccard)**. Jaccard over the two texts restricted to nouns, verbs, numbers, and named entities (spaCy POS tags NOUN, VERB, NUM, PROPN). Targets the factual-flip failure mode: a date changed (3pm → 4pm), a name changed (Mike → Mark), an amount changed ($500 → $5000). Promote to gate if the diagnostic catches misses that the Levenshtein + cosine pair lets through. Default pass: ≥ 0.85.

Considered, not shipped:

- **ROUGE-L F1**. Captures sequence preservation (kept the bones of the draft). The case it uniquely catches (appended sign-offs that punish Levenshtein) is already softened by stripping signatures upstream. Logged as diagnostic, low priority for promotion.
- **BERTScore F1**. Token-level contextual matching. Reserve as a swap for cosine if cosine underperforms on longer drafts.

A draft passes "as-is" only if both shipped gates pass independently. Treating them as independent gates rather than a weighted sum prevents one strong signal from masking the other's failure: high cosine cannot rescue a high-Levenshtein miss when the user has rewritten the substance.

**Threshold calibration**. The defaults above are bootstrapped guesses. For the first ~50 drafted-vs-sent pairs, run an LLM judge (gpt-4o, prompt: "did the user preserve the intent of this draft? pass / partial / fail") and refit each threshold to maximize agreement with the verdict. Cost ~$0.50 per recalibration. Re-run as the dataset grows.

**Attribution**. Triage is currently fused into the drafter — the same LLM that writes a draft is implicitly deciding the email is worth drafting in the first place. Once the triage classifier ships in Bucket 4, that decision becomes observable as a separate signal and the attribution columns in the send-rate rubric become computable. Pre-Bucket-4, "user replied manually" outcomes are logged but not attributed; the data carries forward unchanged once triage is extracted.


### 2. Latency

**Definition.** Wall-clock time from email arrival in Gmail to draft appearing in Slack for review.

**Two views, both required:**

- **Per-draft (p50, p95).** Single-email latency. Catches per-call regressions (e.g. switching to a slower model).
- **Per-batch (total, p95).** Time to complete a full inbox-processing run of N emails. Catches workflow-level regressions (e.g. serialization that disappears in single-draft tests).

**Why both.** A per-draft win can be a per-batch loss if it's bought with more parallelism than the rate limits allow. Per-batch is what the user actually feels.

### 3. Cost per draft

**Definition.** `(input_tokens × input_rate) + (output_tokens × output_rate)`, summed across every LLM call in the pipeline for a single draft.

**Per-stage breakdown.** Reported alongside the total. With v1.0 components in place, the stages are: triage → retrieval query rewriting → embedding lookup (free if local) → draft generation. LangSmith already attributes tokens per call; aggregation per stage is a wrapper, not new instrumentation.

**Why per-stage matters even though the gold metric is the total.** The model-tiering hypothesis (cheap classifier + flagship drafter for hard cases) is a structural change to the cost shape, not just a number reduction. The per-stage breakdown is what makes the hypothesis testable; the total is what gets reported.

---

## What's deliberately not gold

### Edit distance as a standalone metric

Folded into the send rate grading rubric above. As its own metric, it answered the same question as send rate but with more noise. Threshold-gating it into the pass/fail of send rate keeps the signal and drops the redundancy.

### Inbox-zero session completion rate

Likely redundant with per-batch latency and send rate at the aggregate. Deferred unless a failure mode shows up that the three gold metrics miss.

### Component diagnostics

Triage classifier accuracy, RAG retrieval quality, embedding model selection, and hot/cold cache behavior are all component-level concerns. Their effect on the system shows up in the three gold metrics above; their tuning happens in component-specific brainstorms and ADRs, not here.

---

## Capture surface

| Metric | Data source | Implementation status |
|---|---|---|
| Send rate (Slack action) | Slack button-press events | Exists in Bolt handler |
| Send rate (Gmail outcome) | Gmail folder polling (Sent / Drafts) | Needed; lives in Bucket 2 feedback collection |
| Edit distance | Diff between drafted body and sent body in Gmail | Computed in harness |
| Latency per draft | `time.perf_counter()` around the pipeline | Trivial |
| Latency per batch | LangSmith trace span on the batch workflow | Already captured |
| Cost per draft | LangSmith token usage × OpenRouter pricing table | Already captured |

---

## Open questions

1. What's the right window for "Save Draft → user sends later" to count as a pass? Default 24h is a guess.
2. Should disagreement between the two shipped gates (Levenshtein passes, cosine fails, or vice versa) trigger a "partial" send-rate result for diagnostic review, or stay collapsed into binary pass/fail? Current default: collapse to fail and surface the disagreement in logs.
3. Pre-classifier, should we report send rate as one number (conflated) or two (best-case / worst-case attribution bounds)?

---

## Decision

The three gold metrics for v1.0 are **send rate**, **latency** (per-draft and per-batch), and **cost per draft**. Every v1.0 component (RAG, classifier) is measured against the v0.x baseline on these three. Component-specific diagnostics are added to the harness as those components arrive but do not displace the gold tier.
