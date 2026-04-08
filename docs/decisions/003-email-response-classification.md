# 003 — Email Response Classification: Lightweight Gating Before LLM Draft Generation

**Status:** Proposed  
**Date:** 2026-04-06  

---

## Context

`_process_emails_for_drafts` currently sends every unread email to the LLM regardless of whether it warrants a reply. Emails like OOO notifications, payment confirmations, and FYI blasts consume the same tokens and latency budget as an action item or a direct question — but require no response at all.

This creates two compounding costs:

1. **Token waste.** Every email that doesn't need a reply still costs input tokens for classification, body formatting, and system prompt overhead.
2. **Latency.** Even with ADR 002 parallelisation, the ceiling is the slowest individual LLM call. Eliminating no-response emails before that stage removes calls entirely, not just parallelises them.

The hypothesis is that "does this email require a response?" is a much simpler task than "write a good reply". An LLM may not even be needed here.
---

## Goal

Build an evaluation harness to measure the accuracy and cost of different classification mechanisms on a labelled email dataset, then use those results to decide what gates `_process_emails_for_drafts`.

---

## Evaluation Design

### Target variable

Binary: `draft_warranted: bool`

| Label | Meaning |
|---|---|
| `True` | Email requires a substantive reply drafted by the LLM |
| `False` | Email can be ignored, auto-archived, or acknowledged without an LLM call |

### Ground truth dataset

A `ClassificationCase` wrapper carries the label alongside the email:

```python
from dataclasses import dataclass
from src.models.gmail import EmailMessage

@dataclass
class ClassificationCase:
    email: EmailMessage
    draft_warranted: bool
    category: str  # human-readable label for analysis: action_item, question, ooo, payment, fyi
```

The eval dataset should cover at minimum:

| Category | `draft_warranted` | Rationale |
|---|---|---|
| `action_item` | `True` | Direct ask with a deadline; silence is a miss |
| `question` | `True` | Requires an answer |
| `ooo` | `False` | Auto-reply; responding creates noise |
| `payment_confirmation` | `False` | Transactional receipt; no reply needed |
| `fyi` | `False` | Informational broadcast |
| `newsletter` | `False` | No sender expects a reply |
| `calendar_invite` | `True`/`False` | Context-dependent; useful ambiguous case |
| `thread_reply_to_you` | `True` | Continuation of a conversation you started |

### Metrics

- **Precision** — of emails the classifier flags as `draft_warranted=True`, what fraction actually are? Low precision wastes LLM calls on emails that don't need them.
- **Recall** — of emails that actually warrant a draft, what fraction does the classifier catch? Low recall means missed replies, which is the worse failure mode.
- **F1** — harmonic mean
- **Cost per email** — total API spend / number of emails classified (input tokens × rate + output tokens × rate)
- **Latency per email** — wall-clock ms from email in to label out
- **Total token spend** — prompt tokens + completion tokens per classification call, to compare model efficiency

A target operating point: **recall ≥ 0.95, precision ≥ 0.80**. Missing a reply that was needed (low recall) is worse than occasionally sending an unnecessary LLM call (low precision).

---

## Existing Datasets to Consider

Rather than generating a synthetic dataset from scratch, the following real-world corpora provide email text that can be relabelled with `draft_warranted`:

**[Enron Email Dataset](https://www.cs.cmu.edu/~enron/)** — ~500k real professional emails from Enron employees. The largest open email corpus available. Covers a wide range of email types including action items, FYIs, meeting coordination, and newsletters. Requires relabelling but best candidate for scale.

**[Avocado Research Email Collection](https://catalog.ldc.upenn.edu/LDC2015T03)** — ~75k emails from a defunct tech company. More domain-relevant than Enron (software/product context). Requires LDC licence (free for research).

**[AESLC — Abstractive Email Subject Line Corpus](https://github.com/ryanzhumich/AESLC)** — ~18k emails from the Enron corpus, cleaned and filtered. Smaller but higher quality text. Originally built for summarisation; can be repurposed.

**[EmailSum](https://github.com/ZhengHui-Z/EmailSum)** — email thread summarisation dataset. Thread-level rather than message-level, which maps well to how `_read_unread_emails` works (fetching threads, not isolated messages).

**Synthetic generation** — use GPT-4o to generate 200–500 labelled `(email_body, draft_warranted)` pairs across all categories above. Faster to bootstrap than relabelling a corpus, and you control the distribution. Risk: the eval dataset and the LLM classifier may share the same biases. Mitigate by using a different model for generation than for classification.

Recommended starting point: **synthetic generation for the initial eval** (fast, controlled, no data licence concerns), with a plan to validate on a sample of relabelled Enron emails before treating results as definitive.

---

## Classification Mechanisms to Evaluate

Ordered roughly from cheapest to most capable:

**Heuristic (no model)**
Regex and keyword rules: detect OOO phrases, payment confirmation patterns, unsubscribe footers, newsletter sender domains. Zero cost, zero latency, brittle on edge cases. Useful as a pre-filter before any model call.

**Zero-shot NLI (local, no API cost)**
`facebook/bart-large-mnli` or `cross-encoder/nli-MiniLM2-L6-H768` run locally. Classify against the hypothesis "This email requires a reply." No fine-tuning required, no API spend. Latency depends on hardware; on CPU expect 50–200ms per email.

**Shallow Models + Fine-tuning (local, no API cost)**

These approaches train on the labelled dataset produced in Next Step 1. Once trained, inference is free and runs in under 5ms per email on CPU — orders of magnitude faster than any API call. The tradeoff is that they require a sufficient labelled dataset and degrade on out-of-distribution email types not seen during training.

*Naive Bayes*
The simplest viable baseline. Treats the email body as a bag of words and learns a probability distribution over tokens per class. Trivially fast to train (seconds on 200 examples) and to infer (<1ms). Interpretable — you can inspect which tokens drive the `draft_warranted=True` prediction. Struggles with negation and word order ("I do *not* need a reply" and "I need a reply" look similar), but often surprisingly competitive on short, formulaic emails like OOO and payment confirmations. Start here to establish a floor before investing in anything heavier.

*FastText*
Facebook's word-embedding classifier. Learns subword embeddings alongside the classification head, giving it better generalisation than Naive Bayes on unseen vocabulary (e.g. new sender domains, product names). Trains in seconds on CPU, infers in under 1ms, and ships as a single binary with no runtime dependencies. A strong candidate for a production heuristic layer — lightweight enough to bundle directly with the Flask app. Pretrained embeddings (`cc.en.300.bin`) can be used to reduce the labelled data requirement further.

*Fine-tuned DistilBERT*
A 66M parameter distilled version of BERT that retains ~97% of BERT's accuracy at 60% of the size and 2× the speed. Fine-tune the final classification head (and optionally the top transformer layers) on the labelled dataset using HuggingFace `transformers`. Expects tokenised input rather than raw bag-of-words, so it captures word order and context that Naive Bayes and FastText miss. On CPU, inference is ~20–50ms per email; on MPS (Apple Silicon) or a small GPU, ~2–5ms. The most accurate local option short of a full LLM. Recommended if Naive Bayes and FastText fall short of the recall ≥ 0.95 threshold on ambiguous categories like `calendar_invite` and `thread_reply_to_you`.

**SetFit (few-shot fine-tuned sentence transformer)**
Fine-tune a small sentence transformer (`all-MiniLM-L6-v2`) on 8–32 labelled examples per class using the SetFit framework. Produces a model that runs locally with no per-call cost after training. Strong candidate if the synthetic dataset approach is used for fine-tuning.

**Small LLM via API**

| Model | Input $/1M tokens | Output $/1M tokens | Notes |
|---|---|---|---|
| `google/gemini-flash-1.5` | ~$0.075 | ~$0.30 | Fastest API option |
| `openai/gpt-4o-mini` | $0.15 | $0.60 | Already in stack via OpenRouter |
| `meta-llama/llama-3.1-8b-instruct` | ~$0.06 | ~$0.06 | Cheapest API LLM option |
| `anthropic/claude-haiku-3` | $0.25 | $1.25 | Strong instruction following |

**Full LLM (current behaviour baseline)**
`openai/gpt-4o` or equivalent via `_process_emails_for_drafts`. This is the control — everything else is measured against it for accuracy, and the goal is to match its recall at lower cost.

---

## Proposed Architecture: Two-Stage Multi-Agent Pipeline

```
                    ┌─────────────────┐
                    │  GmailReader    │
                    │  read_emails()  │
                    └────────┬────────┘
                             │  List[EmailMessage]
                             ▼
                    ┌─────────────────┐
                    │  Classifier     │  ← lightweight: heuristic / small model / fine-tuned
                    │  Agent          │
                    └────────┬────────┘
                             │  List[ClassificationCase]
               ┌─────────────┴─────────────┐
               │ draft_warranted=False      │ draft_warranted=True
               ▼                           ▼
        archive / skip            ┌─────────────────┐
                                  │  Draft          │
                                  │  Agent          │  ← current LLM (_process_emails_for_drafts)
                                  └─────────────────┘
```

The classifier agent is a new, independently testable component. If the eval shows a heuristic or local model meets the recall threshold, no LLM call is made for that stage at all. If a small API model is needed, it runs in parallel (ADR 002 pattern) across all emails before any draft generation begins.

This also enables independent iteration: the draft quality and the classification accuracy can be improved separately without touching each other.

---

## Test Structure

```
tests/
  evals/
    __init__.py
    test_draft_classification.py   ← accuracy metrics, marked @pytest.mark.eval
  fixtures/
    email_datasets.py              ← ClassificationCase + dataset constants live here
```

The `@pytest.mark.eval` marker excludes these from the default CI run (they require API keys and spend money). Run explicitly:

```bash
pytest tests/evals/ -m eval -s --log-cli-level=INFO 2>&1 | tee experiments/classification_eval_$(date +%Y%m%d).txt
```

---

## Open Questions

1. Which existing dataset to use for validation beyond synthetic — Enron or Avocado?
2. What is the acceptable precision/recall tradeoff? Is a missed reply ever acceptable, or is recall always the priority?
3. Should the classifier be a standalone service or a method on a new `ClassifierAgent` class within the existing architecture?
4. If a local model (SetFit/NLI) is chosen, what is the deployment story — bundled with the app, or a separate process?

---

## Next Steps

1. Generate a synthetic labelled dataset (200 examples, 8 categories) using GPT-4o
2. Wrap in `ClassificationCase` and add to `tests/fixtures/email_datasets.py`
3. Implement a baseline heuristic classifier and measure precision/recall against the dataset
4. Run the same dataset against `gpt-4o-mini` and `llama-3.1-8b` via OpenRouter and record cost per email
5. Decide mechanism based on results; write implementation ADR
