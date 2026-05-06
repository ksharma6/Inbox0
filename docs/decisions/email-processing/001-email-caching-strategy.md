# 001 — Email Caching Strategy

**Status:** Proposed  
**Date:** 2026-04-05  
**Branch:** `docs/decisions/email_cache_strategy`

---

## Context

During a demo, the workflow stalled noticeably while processing an inbox containing a ~40-email thread. The root cause is that every time `EmailProcessingWorkflow.run()` is triggered, **all emails are re-fetched from the Gmail API and re-formatted into a prompt from scratch**, regardless of whether they have been seen before.

The three compounding issues:

1. **No thread-scoped fetch.** `get_recent_emails_in_thread` calls `read_emails` with `thread_id` declared as a parameter but **never applied** to the Gmail API querys.
```python
#gmail_reader.py 90-103
    def get_recent_emails_in_thread(
        self, thread_id: str, count: int = 4
    ) -> List[EmailMessage]:
        """
        Get the most recent emails in thread specified by thread_id.

        Args:
            thread_id (str): Unique Gmail thread identifier.
            count (int): Maximum number of messages to return.

        Returns:
            List[EmailMessage]: Messages from the given thread, if available.
        """
        return self.read_emails(count=count, thread_id=thread_id)

```
```python
#gmail_reader.py lines 61-73
        query_parts = ["in:inbox"]

        if primary_only:
            query_parts.append("category:primary")

        if unread_only:
            query_parts.append("is:unread")

        query = " ".join(query_parts)

        # list of user's messages - capped at 25 messages
        list_params = {"userId": "me", "maxResults": min(count, 25), "q": query}
```

 The method falls back to a generic inbox `messages.list`, so the "last 2 from this thread" intent is silently broken.

2. **No body truncation.** Full HTML-stripped bodies are concatenated into `emails_text` and embedded verbatim in the user prompt. There is no character or token cap on individual message bodies.

3. **No message-level cache.** Each workflow invocation starts cold: Gmail API fetch → HTML strip → `EmailMessage` model → format to string → LLM prompt. Previously seen messages in a thread are fully reprocessed each time.

The combined effect: a 40-email thread means the LLM receives a prompt containing all 40 bodies, and latency grows with every new reply added to the thread.

---

## Hypothesis

> When a new email arrives in an existing thread, the total prompt token count grows linearly with the number of emails in that thread, and LLM latency grows proportionally. Caching previously seen messages and only presenting new ones (plus a short thread summary) will reduce token count and latency sub-linearly relative to thread depth.

`Agent._timed_completion` now logs `estimated_prompt_tokens`, `prompt_tokens`, `completion_tokens`, and `elapsed_ms` per LLM call, giving us the instrumentation needed to measure this hypothesis.

---

## Decision

Implement a **lightweight message-level cache** backed by the existing `StateManager` (currently used for draft approval state). For each processed email thread, store:

- A set of `message_id`s that have already been seen and processed.
- A short LLM-generated thread summary (≤ 200 tokens) that represents the full prior context.

On the next workflow run for a thread, the prompt becomes:
```
Thread summary (cached): <200-token summary>

New messages since last run:
```


This avoids re-feeding the full thread on every trigger while preserving enough context for the LLM to generate coherent drafts. 

---

## Alternatives Considered

### A. API-level prompt caching (OpenAI/OpenRouter)
Pass the full thread as a cached prefix using the OpenAI prompt cache feature. Reduces inference cost but still requires sending the full prompt on cache miss (i.e., first encounter or cache expiry). Does not address the token-count growth problem; only amortises cost on repeated identical prompts. Rejected as the primary mechanism but worth layering on top.

### B. Body truncation only
Cap each `email.body` to a fixed character/token limit before embedding in the prompt. Reduces worst-case token count but does not scale: a 40-email thread with 500-token-capped bodies still sends 20 000 tokens per run. Does not address re-processing. Kept as a complementary safeguard regardless of which option is chosen.

### C. Full in-memory thread transcript
Maintain the full `messages[]` array (system + user + assistant + tool) across workflow runs so the LLM sees its own prior analysis as conversation history. Most semantically accurate but memory-intensive, stateful across process restarts, and requires careful invalidation when emails are modified/deleted. Rejected for initial implementation; revisit if summary-based approach loses too much context.

### D. Do nothing
Current behaviour produces correct results but degrades O(n) in thread depth. Acceptable for short threads; unacceptable for production use with real inboxes. Rejected.

### E. Vector store with semantic retrieval (Redis / SQLite-vec / Chroma)

Embed each `EmailMessage.body` at write time and store vectors in a dedicated store (e.g. Redis Stack with `HNSW`, `sqlite-vec`, or an embedded Chroma instance). On each workflow run, embed the new incoming message and retrieve the top-k most semantically similar historical emails to include as context.

**Where this is the right answer:**
- Recall across threads: surfacing a relevant prior conversation with the same sender without scanning the whole inbox.
- A growing personal knowledge base where context spans months of email history.
- When thread depth alone does not capture the relevant context (e.g. a new email references a decision buried in a separate thread).

**Why it is deferred here:**
- Adds an embedding model call (cost + latency) for every email stored and every retrieval. For a 40-email thread that is already slow, this adds a second round-trip before the LLM call.
- Thread conversations are inherently sequential — email 38 is contextually downstream of email 37 whether or not they are semantically similar. Ranking by cosine similarity can surface the wrong messages when a thread shifts topic mid-conversation.
- Requires standing up and maintaining a vector index that the current stack (Flask + LangGraph + pickle StateManager) has no equivalent of. The infra cost is non-trivial for a problem that can be solved with a lightweight summary.
- Cache invalidation is harder: updating or deleting an email requires re-embedding and re-indexing, not just removing a key from a dict.

**Verdict:** Deferred, not rejected. Revisit when the use case expands to cross-thread recall or multi-session inbox memory. At that point, `sqlite-vec` (zero extra infra, ships as a SQLite extension) is the lowest-friction entry point; Redis Stack is appropriate if the app moves toward a multi-user deployment that needs concurrent writes and sub-millisecond search.
---

## Consequences

**Positive**
- Token count per workflow run is bounded by (summary size + new messages), not total thread depth.
- Latency scales with delta emails, not thread length.
- `StateManager`'s existing pickle-based storage can be extended without a new persistence layer.

**Negative / Risks**
- Thread summaries may lose nuance. If the summary omits a detail needed for a new reply, the draft will miss context.
- Cache invalidation: if a sender edits or retracts an earlier email, the cached summary will not reflect this (low probability via Gmail but worth noting).
- The `thread_id` bug in `read_emails` must be fixed as a prerequisite—otherwise the cache key (Gmail `thread_id`) is never properly used to scope fetches.

---

## Testing Plan

The goal is to **confirm the hypothesis** before committing to a full implementation. All tests use existing `_timed_completion` log output (tokens + `elapsed_ms`) as the measurement surface.

### Prerequisite: fix `get_recent_emails_in_thread`

The `thread_id` parameter in `read_emails` must be wired up to the Gmail API query before any thread-level behaviour can be tested meaningfully.

```python
# gmail_reader.py — proposed fix (not yet applied)
if thread_id:
    query_parts.append(f"threadId:{thread_id}")

### Results
The hypothesis understated the problem. Token growth is not linear — it is
exponential, driven by the quoted-reply structure of real email threads. Each
message re-embeds the full content of all prior messages, producing a prompt
that grows as O(2^N) with thread depth rather than O(N).

| Step | Tokens | Growth factor |
|---|---|---|
| depth 5 | 739 | baseline |
| depth 10 | 2,529 | **3.4×** |
| depth 20 | 10,759 | **4.3×** |
| depth 40 | 56,319 | **5.2×** |

At depth 40, the prompt reaches **56k tokens** before any LLM call is made.
At current OpenRouter pricing for GPT-4o (~$5/1M input tokens), a single
workflow run on this thread costs ~$0.28 in input tokens alone and repeats
that cost in full on every subsequent trigger, since nothing is cached.

The message-level cache described in this ADR directly addresses the
compounding mechanism: once a message has been processed and summarised, it
is never re-embedded. The prompt for a new reply becomes:
- Thread summary (cached, ~200 tokens)
- New message (1 reply, ~50–300 tokens)

**Implementation is no longer optional.** The exponential growth rate means
that production inboxes with active threads will hit model context limits
(128k tokens for GPT-4o) at thread depths reachable within a single working
day of back-and-forth.

Raw measurements: [`reports/adr001_token_growth.csv`](../../../reports/adr001_token_growth.csv)
