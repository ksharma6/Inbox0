# 002 — Parallelization Strategy for Workflow Latency

**Status:** Proposed  
**Date:** 2026-04-05  
**Related:** [001 — Email Caching Strategy](001-email-caching-strategy.md)

---

## Context

The `EmailProcessingWorkflow` has two sequential loops that each introduce avoidable cumulative latency. Unlike the token-count problem addressed in [001](001-email-caching-strategy.md), this is not a caching problem — the underlying operations are already correct and independent of each other. The issue is that they are executed one at a time when they could fire concurrently.

### Loop 1 — Gmail API fetches in `_read_unread_emails`

```python
# workflow.py lines 124–131
for email in unread_emails:
    thread_emails = self.gmail_reader.get_recent_emails_in_thread(
        email.thread_id, count=2
    )
    recent_emails.extend(thread_emails)
```

For 5 unread emails, this makes 5 sequential `messages.list` calls to the Gmail API. Each is an independent HTTP round-trip (~100–500 ms). Total: up to ~2.5 s of serial network I/O where all 5 calls could resolve in parallel in ~500 ms.

### Loop 2 — Draft generation in `_create_draft_responses`

```python
# workflow.py lines 287–319
for email_info in state.processed_emails:
    draft_content = self._generate_draft_response(email, email_info)
```

Each `_generate_draft_response` call is an independent LLM request. With 3 emails requiring drafts at ~5 s per call, the total is ~15 s. Parallelising gives ~5 s — the cost of the slowest single call.

---

## Background: Parallelism in LLM Systems

There are three distinct levels of parallelism in an LLM-based system, operating at different layers:

**Hardware (server-side, not controllable)**  
The transformer attention mechanism processes all token positions simultaneously across GPU cores during the prefill phase. This is already happening on the API provider's infrastructure.

**Speculative decoding (server-side, provider-dependent)**  
A small draft model generates candidate tokens; the large model verifies a batch in one forward pass rather than one token at a time. Reduces decode latency without changing output quality. Exposed by some providers (Groq, Fireworks). Relevant when choosing inference providers for latency-sensitive deployments.

**Request-level (client-side — applicable here)**  
Multiple independent API requests or I/O calls fire concurrently from the client. This is fully within our control and requires no changes to model, provider, or architecture — only the call site.

---

## Hypothesis

> The two sequential loops account for a meaningful and measurable share of end-to-end workflow latency. Parallelising them with `ThreadPoolExecutor` will reduce total wall-clock time proportionally to the number of concurrent calls, with no change to output quality.

`Agent._timed_completion` already logs `elapsed_ms` per LLM call. Gmail API call duration can be measured by wrapping `get_recent_emails_in_thread` with `time.perf_counter`. Together these give a sufficient baseline.

---

## Decision

Apply `concurrent.futures.ThreadPoolExecutor` to both loops. The change is localised to two methods in `workflow.py` and requires no interface changes elsewhere.

### Loop 1 — Parallel thread fetches

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _read_unread_emails(self, state: GmailAgentState) -> GmailAgentState:
    unread_emails = self.gmail_reader.read_emails(
        count=5, unread_only=True, include_body=True, primary_only=True
    )

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(
                self.gmail_reader.get_recent_emails_in_thread, email.thread_id, 2
            ): email
            for email in unread_emails
        }
        recent_emails = []
        for future in as_completed(futures):
            recent_emails.extend(future.result())

    state.unread_emails = list({e.id: e for e in recent_emails}.values())[:5]
    return state
```

### Loop 2 — Parallel draft generation

```python
def _create_draft_responses(self, state: GmailAgentState) -> GmailAgentState:
    if not state.processed_emails:
        return state

    def generate_one(email_info):
        email = next((e for e in state.unread_emails if e.id == email_info["email_id"]), None)
        if not email:
            return None
        draft_content = self._generate_draft_response(email, email_info)
        try:
            draft = self.gmail_writer.create_draft(
                sender=email.to_email,
                recipient=email.from_email,
                subject=f"Re: {email.subject}",
                message=draft_content,
            )
            return {
                "email_id": email_info["email_id"],
                "draft": draft,
                "priority": email_info["priority"],
                "original_email": email,
                "draft_content": draft_content,
            }
        except Exception as e:
            logger.error(f"Error creating draft for email {email_info['email_id']}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=len(state.processed_emails)) as executor:
        results = list(executor.map(generate_one, state.processed_emails))

    state.draft_responses = [r for r in results if r is not None]
    return state
```

---

## What Is Not Parallelisable

The LangGraph pipeline nodes are intentionally sequential — each step depends on the output of the previous one:

```
fetch → summarise → analyse → draft → send to Slack
```

This dependency chain is real and correct. Parallelism is a within-node optimisation, not an across-node one.

The `_generate_email_summary` and `_process_emails_for_drafts` LLM calls each take all emails as a single combined prompt. Splitting them into per-email parallel calls would change the semantics (the model loses cross-email context) and increase total token spend. Not recommended.

---

## Alternatives Considered

### asyncio instead of ThreadPoolExecutor
`asyncio` is the idiomatic approach for I/O-bound concurrency in Python but requires the Gmail client and OpenAI SDK to expose `async` interfaces. The `googleapiclient` library is synchronous; the `openai` Python SDK exposes `AsyncOpenAI` but `Agent` wraps the synchronous client. Migrating both is a larger refactor. `ThreadPoolExecutor` achieves the same concurrency for I/O-bound work on threads without requiring interface changes. Revisit if the codebase migrates to `async` end-to-end.

### LangGraph parallel nodes
LangGraph supports parallel node execution via fan-out edges. This would require restructuring the graph and adds coupling between the graph topology and the concurrency model. Deferred — `ThreadPoolExecutor` within a node is simpler and easier to test in isolation.

---

## Consequences

**Positive**
- Gmail fetch step goes from serial (~2.5 s worst case) to concurrent (~500 ms worst case) with no logic changes.
- Draft generation goes from `N × call_time` to `max(call_times)` — effectively the cost of the slowest single draft.
- No new dependencies; `concurrent.futures` is stdlib.
- Each loop remains independently testable.

**Negative / Risks**
- Gmail API rate limits: 5 concurrent `messages.list` calls per workflow run is well within Gmail API quotas (250 units/s for `messages.list`), but worth monitoring if run frequency increases.
- OpenRouter/OpenAI rate limits: parallel draft calls count as concurrent requests against per-minute token limits. With 3–5 drafts this is unlikely to be an issue; at higher scale, add a semaphore to cap concurrency.
- Error handling: `as_completed` surfaces exceptions per-future. The proposed implementation logs and skips failed drafts, consistent with the existing sequential behaviour.

---

## Combined Latency Estimate

| Step | Before | After caching (ADR 001) | + Parallelisation (this ADR) |
|---|---|---|---|
| Gmail API fetches | ~2.5 s (5 serial) | ~0.5 s (1 new msg) | ~0.3 s (concurrent) |
| LLM prefill (40-email thread) | ~15–20 s | ~1–2 s (summary + delta) | same |
| Draft generation (3 drafts) | ~15 s (serial) | ~15 s (serial) | ~5 s (concurrent) |
| **Total (rough)** | **~30–40 s** | **~17–18 s** | **~7–8 s** |

Caching (ADR 001) dominates the win on the prefill bottleneck. Parallelisation dominates on draft generation. Both are needed for a responsive end-to-end experience.

---

## Testing Plan

### Test 1 — Baseline serial latency (Gmail fetches)

Patch `get_recent_emails_in_thread` to sleep for a fixed duration (e.g. 200 ms). Assert that the current sequential implementation takes ≥ `5 × 200 ms = 1000 ms`. Assert that the parallel implementation takes < `300 ms`.

### Test 2 — Baseline serial latency (draft generation)

Patch `_generate_draft_response` to sleep for 500 ms. With 3 processed emails, assert serial time ≥ 1500 ms and parallel time < 700 ms.

### Test 3 — Error isolation

Patch one of three `_generate_draft_response` calls to raise an exception. Assert that the remaining two drafts are still returned in `state.draft_responses` and the failed one is absent — matching existing error-handling behaviour.
