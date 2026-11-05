# 002 — Shadow Mode: Safe Candidate-Dataset Collection

**Status:** Proposed
**Date:** 2026-05-17

---

## Context

[001-gold_metrics.md](001-gold_metrics.md) commits Inbox0 to scoring v1.0 on three system-level signals (send rate, latency, and cost per draft) and to growing a labeled dataset toward 50 calibration examples before any threshold becomes load-bearing. The immediate need is a safe way to run the real pipeline on a real inbox and retain candidate evaluation examples without sending email into the wild every time the agent thinks it should.

Today the gold-metric inputs are scattered:

- Slack button-click events live as log lines.
- Workflow state is pickled to memory or a file by `StateManager`.
- LLM token usage is appended to `usage_tracker.json` with `timestamp`, `model`, `prompt_tokens`, `completion_tokens`
    — There is presently no `workflow_run_id`, `draft_id`, or stage label.
- "Draft surfaced in Slack" and "email arrived" timestamps exist only as the byproduct of `chat_postMessage` and `email.date`, which is the sender's clock, not Inbox0's ingest time.

These can't be joined into a per-draft record without a collection layer that exists before the components it scores. Shadow mode is part of that layer. Its primary output is a durable candidate dataset containing the input/context used by the pipeline, the generated draft, the user's action, and operational telemetry. A shadow example is not automatically a gold example: `Would Send`, `Would Edit`, and `Would Reject` are intent labels, not observed outcomes or human-authored target responses. This ADR scopes the **collection layer only**. Reporters, edited-response capture, edit-distance gates, and the LLM-judge threshold calibration described in 001 are explicit follow-ons.

---

## Goals

1. Run the existing workflow against a real inbox with one safety property: **shadow mode performs no Gmail mutations**, regardless of which review action the user selects.
2. Emit a durable, append-only candidate record containing the pipeline input/context, generated draft, user action, join keys, and every event needed to compute per-draft latency, per-batch latency, and per-draft cost offline.
3. Collect a coarse draft-quality judgment: acceptable as generated (`Would Send`), useful but requiring intervention (`Would Edit`), or not useful enough to continue with (`Would Reject`).
4. Be instrumentation, not a fork. No parallel `DraftApprovalHandler`, no second workflow class, no copy-paste of the approval flow.

## Non-goals

- Computing the gold metrics inside the app. The math from 001 (cost rates, edit distance, LLM judge) lives in the offline harness.
- Capturing the user's edited response or diagnosing why `Would Edit` was selected. Those require a follow-up editing or reason-labeling surface.
- Replacing `UsageTracker`. It coexists with `EventLog` in this PR; collapsing them is a separate cleanup.
- A pricing table. Tokens and model name are recorded; `(tokens × rate)` is the harness's job so a stale price doesn't get baked into the runtime.
- File rotation for `metrics/*.jsonl`. Start unbounded; revisit when volume warrants.

---

## What gets shadowed and what stays live

The Gmail-side actions split three ways:

| Action          | Live behavior                             | Shadow behavior                                               |
|-----------------|-------------------------------------------|---------------------------------------------------------------|
| `send_draft`    | `messages().send()`; email leaves         | **No-op.** Return `{"id": "shadow_msg_<uuid>"}`. Emit event    |
| `send_reply`    | `messages().send()`; email leaves         | **No-op.** Same shape as above                                 |
| `save_draft`    | `drafts().create()`; drafts folder write  | **No-op.** Return a synthetic shadow result. Emit intent event |
| `create_draft`  | Local base64 encode, no API call          | Unchanged                                                      |

The safety boundary is every Gmail mutation made through the writer. Gmail reads remain live so the pipeline evaluates real inbox data, while send, reply, and save operations are intercepted. This prevents evaluation runs from creating drafts that clutter the account, affect later workflows, or become accidental send candidates.

Reject has no Gmail side effect in either mode.

---

## How the layer plugs in


Four pieces hold this together:

1. **`AppMode` flag.** Read from `SHADOW_MODE` at boot. Default `LIVE`.
2. **`ShadowGmailWriter`.** Subclass of `GmailWriter` that overrides all three Gmail mutation paths: `send_draft`, `send_reply`, and `save_draft`. Each becomes a no-op that returns a clearly synthetic result and emits an event. The factory injects this instead of `GmailWriter` when the flag is on.
3. **`HumanDecision` boundary type.** `DraftApprovalHandler.handle_approval_action` returns a decision object instead of `None`. The Slack route layer translates it into an `EventLog.record_human_decision(decision)` call. The handler stays focused on Slack; persistence lives in the eval layer.
4. **`EventLog`.** Append-only JSONL sink at `metrics/events.jsonl`. One method `record(event_name, **fields)` plus typed helpers per event.

The factory wires all of this. Without `SHADOW_MODE` set, the wiring resolves to today's exact dependency graph minus the (cheap, optional) event-log calls.

---

## Slack button copy

All three shadow-mode actions use hypothetical framing because none mutates Gmail.

| Action  | Live label           | Shadow label        |
|---------|----------------------|---------------------|
| approve | ✅ Approve & Send    | 👍 Would Send       |
| save    | 💾 Save Draft        | ✏️ Would Edit       |
| reject  | ❌ Reject            | 👎 Would Reject     |

`action_id` and `value` strings are identical in both modes so the route dispatch and `ResumeAction` mapping are unchanged.

The labels form a coarse quality scale: `Would Send` means acceptable as generated, `Would Edit` means useful but requiring intervention, and `Would Reject` means not useful enough to continue with. `Would Edit` records the raw user judgment; it does not diagnose why intervention is needed or estimate edit magnitude.

---

## Latency anchors

001 defines latency as "email arrival in Gmail → draft appearing in Slack." The header `Date` is the sender's clock, so the closest defensible anchors Inbox0 owns are:

- `email_first_seen_at` — set when `_read_unread_emails` fetches a message. Recorded on an `email_ingested` event keyed by `email_id`.
- `draft_surfaced_at` — the `chat_postMessage` success in `send_draft_for_approval`. Recorded on a `draft_surfaced` event keyed by `draft_id` + `email_id`.

Per-draft latency = `draft_surfaced.surfaced_at - email_ingested.ingested_at`, joined on `email_id`. Per-batch latency = `workflow_completed.ts - workflow_started.ts`. Both views from 001 are computable.

`time.perf_counter_ns()` for monotonic durations within a process; ISO8601 wall-clock timestamps on every event for cross-process joins.

---

## Storage layout

```
metrics/
├── events.jsonl       # EventLog events
└── llm_calls.jsonl    # extended UsageTracker (now includes workflow_run_id, stage, draft_id)
```

Two files, both append-only JSONL, both joined offline by `workflow_run_id` and `draft_id`. The duplication between `llm_calls.jsonl` and `events.jsonl[event=llm_call_completed]` is intentional in this PR: `usage_tracker.json` already exists and other code reads it; one of the two will get collapsed in a follow-on cleanup once nothing else depends on the old shape.

---

## Information-value contract

In live mode, a generated draft is a product artifact intended to help the user act on an email. In shadow mode, the draft is a **measurement stimulus** intended to elicit a judgment about the system. The LLM work is justified only when the run produces durable evidence that can improve or validate the evaluation corpus.

Every shadow draft used for data collection must retain:

- The source email and relevant thread context presented to the pipeline.
- The generated draft.
- The model and prompt or pipeline version that produced it.
- The raw user judgment: `would_send`, `would_edit`, or `would_reject`.
- Token usage, latency, errors, and the join keys needed to connect those events.

Running the LLM without retaining this record is not an evaluation workflow; it is only a safety dry run. Safety dry runs can be useful for integration verification, but they do not justify routine token spend or produce calibration data.

Shadow mode is opt-in and bounded rather than an always-on parallel workload. Collection may run during deliberate sessions, on a sample of eligible emails, or on cases selected for novelty or uncertainty. Collection should stop when the target dataset has sufficient coverage or when additional examples provide little new information.

Selected shadow examples can be reviewed, corrected where a trusted target is needed, and frozen into the corpus consumed by [003-eval_harness.md](003-eval_harness.md). The harness then reuses those cases for repeatable variant comparisons without requiring another live-inbox collection campaign.

---

## What this PR does not include

These are deferred to follow-on PRs and tracked separately so this collection layer can ship small:

- Offline reporter that reads `events.jsonl` and prints send-rate / latency p50,p95 / cost per draft.
- Edit-distance gates (token Levenshtein, semantic cosine) from 001.
- LLM-judge threshold calibration loop from 001.
- Pricing table for cost-per-draft math.
- File rotation policy for `metrics/*.jsonl`.
- Migration of `UsageTracker` callers onto `EventLog`.

---

## Limitations: shadow mode is a cold-start instrument, not the harness

First, what shadow mode earns outright: **a candidate evaluation dataset plus latency and cost per draft.** The candidate record contains the pipeline input/context, generated output, and user action. Latency and cost are read from the real pipeline executing — per-stage token counts and wall-clock from ingest to draft-surfaced — and neither depends on whether a send happens.

The limitation is the third. The send rate (and the edit distance folded into it) in [001](001-gold_metrics.md) is defined as an **outcome** signal: was the email *sent*, how much did the user *change* it before sending. Shadow mode, by design, intercepts the consequence. So it can only ever collect **intent**, not a sent email or edited target. That gap is real and worth stating plainly:

- **Intent overestimates send rate, but in a known direction.** Clicking `Would Send` costs nothing. Under zero stakes the user rubber-stamps drafts that are merely "good enough" — ones they would tighten or kill if the email were actually going out under their name. This low-stakes bias is systematic and *optimistic*: it inflates the rate rather than scrambling it. That directionality is what makes the signal salvageable — shadow-mode send rate is an upper bound now, and once the [003 harness](003-eval_harness.md) produces real sends, the gap between `Would Send` rate and true send rate can be estimated and shadow data carried forward as a debiased estimator rather than discarded.
- **`Would Edit` is a coarse intervention label, not an edit diagnosis.** It indicates that the draft is useful but not acceptable as generated. It does not distinguish factual errors, tone problems, missing context, timing, or an unnecessary draft.
- **Edit distance is deferred, not discarded.** No shadow action produces a sent or edited body, so shadow mode cannot create a drafted-vs-sent pair on its own. Edited-target capture and retrospective replay belong to the [003 harness](003-eval_harness.md).
- **No Gmail artifact exists to observe later.** This is intentional. Avoiding real shadow drafts prevents evaluation runs from contaminating later workflows, producing duplicates, or requiring Gmail cleanup.

A follow-up reason prompt could classify why `Would Edit` or `Would Reject` was selected, but the raw three-way judgment remains the durable observation. Derived analyses may treat `Would Edit` as likely intervention intent without rewriting it as a definitive cause.

**One conflation to avoid.** Shadow examples are candidate examples, not automatically gold examples. The first ~50 examples used by 001 to calibrate edit-distance thresholds still require trusted targets such as human-edited responses or retrospective drafted-vs-sent pairs. A button click alone does not clear the calibration bar.

The conclusion: shadow mode is a **safe, non-mutating candidate-dataset bootstrap.** It captures real pipeline inputs and outputs, user intent, latency, and cost without changing Gmail state. Behavioral ground truth remains the responsibility of [003-eval_harness.md](003-eval_harness.md).

---

## Relationship to other ADRs

- [evaluation/001-gold_metrics.md](001-gold_metrics.md) — defines what gets measured. This ADR builds the collection surface that makes those measurements computable. The `Capture surface` table in 001 maps cleanly onto the events emitted here.
- [evaluation/003-eval_harness.md](003-eval_harness.md) — the actual evaluation engine. Shadow mode is the cold-start bootstrap that seeds it; 003 owns the deterministic replay and live-observation paths that produce the outcome-defined gold metrics shadow mode cannot.
- [reliability/001-idempotent-write-side-retry-strategy-for-mail-and-slack.md](../reliability/001-idempotent-write-side-retry-strategy-for-mail-and-slack.md) — `EventLog.record` must be side-effect-isolated and safely repeatable; this ADR honors that by writing to JSONL and avoiding any cross-event state.

---

## Open questions

1. ~~Should all three buttons use hypothetical language in shadow mode?~~ **Resolved:** yes. Use `Would Send`, `Would Edit`, and `Would Reject`; none performs a Gmail mutation.
2. Should `email_ingested` events fire per-email or per-batch with a list? Per-email is simpler to join; per-batch is cheaper at high volume. Default: per-email until volume forces a change.
3. When `SHADOW_MODE` is unset, do we still construct an `EventLog` and emit events (so the harness can backfill from live data later), or skip emission entirely? Default proposed: still construct, still emit. The log is cheap and the parallelism is the whole point.

---

## Decision

Implement shadow mode as a five-module evaluation layer under `src/eval/` plus a small number of returning-a-decision changes to existing handlers. The flag is `SHADOW_MODE`, defaults off. When on, every Gmail mutation exposed by the writer (`send_draft`, `send_reply`, and `save_draft`) becomes a no-op with a synthetic result. The Slack surface collects `Would Send`, `Would Edit`, or `Would Reject` while retaining existing action IDs for routing compatibility. The collection layer durably records the pipeline input/context, generated draft, model and pipeline identity, raw user intent, join keys, latency, and token usage. Gmail reads, draft generation, draft review, and LLM calls continue through the live pipeline so the candidate dataset reflects the system under evaluation without changing Gmail state. Shadow collection is opt-in and bounded; routine execution is justified only when it produces durable evidence for the evaluation corpus. Edited-target capture, edit distance, and true send-rate computation remain explicitly out of scope and belong to the [003 harness](003-eval_harness.md).
