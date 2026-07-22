# 002 — Shadow Mode: Safe Candidate-Dataset Collection

**Status:** Proposed
**Date:** 2026-05-17

---

## Context

[001-gold_metrics.md](001-gold_metrics.md) commits Inbox0 to scoring v1.0 on three system-level signals (send rate, latency, and cost per draft) and to growing a labeled dataset toward 50 calibration examples before any threshold becomes load-bearing. The immediate need is a safe way to run the real pipeline on a real inbox and retain candidate evaluation examples without sending email into the wild every time the agent thinks it should.

Today the gold-metric inputs are scattered:

- Slack button-click events live as log lines.
- Workflow state is pickled to memory or a file by `StateManager`.
- LLM token usage is appended to `usage_tracker.json` with `timestamp`, `model`, `prompt_tokens`, `completion_tokens` — no `workflow_run_id`, no `draft_id`, no stage label.
- "Draft surfaced in Slack" and "email arrived" timestamps exist only as the byproduct of `chat_postMessage` and `email.date`, which is the sender's clock, not Inbox0's ingest time.

These can't be joined into a per-draft record without a collection layer that exists before the components it scores. Shadow mode is that layer. Its primary output is a durable candidate dataset containing the input/context used by the pipeline, the generated draft, the user's action, and operational telemetry. A shadow example is not automatically a gold example: `Would Send` is an intent label, while a saved draft that is later edited or sent can eventually become a drafted-vs-sent gold pair. This ADR scopes the **collection layer only**. Reporters, downstream Gmail observation, edit-distance gates, and the LLM-judge threshold calibration described in 001 are explicit follow-ons.

---

## Goals

1. Run the existing workflow against a real inbox with one safety property: **no outbound email is sent**, even when the user clicks "Would Send".
2. Emit a durable, append-only candidate record containing the pipeline input/context, generated draft, user action, join keys, and every event needed to compute per-draft latency, per-batch latency, and per-draft cost offline.
3. Allow the user to keep a useful generated response by saving it as a real Gmail draft, without requiring shadow mode to observe or score what happens to that draft later.
4. Be instrumentation, not a fork. No parallel `DraftApprovalHandler`, no second workflow class, no copy-paste of the approval flow.

## Non-goals

- Computing the gold metrics inside the app. The math from 001 (cost rates, edit distance, LLM judge) lives in the offline harness.
- Polling Gmail to determine whether a saved draft was edited or sent. Shadow mode retains the generated body, thread ID, and Gmail draft ID so that capability can be added later.
- Replacing `UsageTracker`. It coexists with `MetricRecorder` in this PR; collapsing them is a separate cleanup.
- A pricing table. Tokens and model name are recorded; `(tokens × rate)` is the harness's job so a stale price doesn't get baked into the runtime.
- File rotation for `metrics/*.jsonl`. Start unbounded; revisit when volume warrants.

---

## What gets shadowed and what stays live

The Gmail-side actions split three ways:

| Action          | Live behavior                              | Shadow behavior                                            |
|-----------------|--------------------------------------------|------------------------------------------------------------|
| `send_draft`    | `messages().send()` — email leaves         | **No-op.** Return `{"id": "shadow_msg_<uuid>"}`. Emit event |
| `send_reply`    | `messages().send()` — email leaves         | **No-op.** Same shape as above                              |
| `save_draft`    | `drafts().create()` — drafts folder write  | **Unchanged.** Create a real Gmail draft and retain its ID  |
| `create_draft`  | Local base64 encode, no API call           | Unchanged                                                   |

The safety boundary is outbound email, not all Gmail writes. Shadow mode intercepts both send paths, while an explicit `Save Draft` action performs the same non-sending Gmail write as live mode. This lets useful shadow output enter the user's normal workflow and preserves the association between the generated body and a real Gmail draft without requiring edit-distance or folder-polling machinery in this ADR.

Reject has no Gmail side effect in either mode.

---

## How the layer plugs in

```mermaid
flowchart TB
    Gmail[Gmail API] -->|read_emails| WF[EmailProcessingWorkflow]
    WF -->|LLM calls with run_id, stage, draft_id| Agent
    WF -->|send_draft_for_approval| DAH[DraftApprovalHandler]
    DAH -->|chat_postMessage| Slack
    Slack -->|button click| Routes[slack_routes]
    Routes -->|handle_approval_action| DAH
    DAH -->|returns ApprovalOutcome| Routes
    DAH -->|send_draft or save_draft| Writer{GmailWriter or ShadowGmailWriter}
    Routes -->|record_approval_outcome| Recorder[(MetricRecorder)]
    WF -->|workflow and draft events| Recorder
    Agent -->|llm_call_completed| Recorder
    Writer -->|email_send_shadowed| Recorder
```

Four pieces hold this together:

1. **`AppMode` flag.** Read from `INBOX0_SHADOW_MODE` at boot. Default `LIVE`.
2. **`ShadowGmailWriter`.** Subclass of `GmailWriter` that overrides the two outbound write paths — `send_draft` and `send_reply` — to no-op and emit an event. It inherits the real `save_draft` behavior. The factory injects this instead of `GmailWriter` when the flag is on.
3. **`ApprovalOutcome` boundary type.** `DraftApprovalHandler.handle_approval_action` returns an outcome object instead of `None`. The Slack route layer translates it into a `MetricRecorder.record_approval_outcome(outcome)` call. The handler stays focused on Slack; persistence lives in the eval layer.
4. **`MetricRecorder`.** Append-only JSONL sink at `metrics/events.jsonl`. One method `record(event_name, **fields)` plus typed helpers per event.

The factory wires all of this. Without `INBOX0_SHADOW_MODE` set, the wiring resolves to today's exact dependency graph minus the (cheap, optional) recorder calls.

---

## Module layout

New code lives under `src/eval/`:

- `app_mode.py` — `AppMode(LIVE, SHADOW)`; `get_app_mode()` reads `INBOX0_SHADOW_MODE`.
- `metric_recorder.py` — append-only JSONL sink. Side-effect-isolated so retries are safe per [reliability/001](../reliability/001-idempotent-write-side-retry-strategy-for-mail-and-slack.md).
- `metric_events.py` — frozen Pydantic models for `WorkflowStarted`, `EmailIngested`, `DraftCandidateRecorded`, `DraftSurfaced`, `ApprovalOutcomeRecorded`, `LLMCallCompleted`, `EmailSendShadowed`, `WorkflowCompleted`. All carry `workflow_run_id`; event-specific events also carry `draft_id` and/or `email_id` and `thread_id`. `DraftCandidateRecorded` durably stores the source input/thread context used by the pipeline and the generated body so the JSONL output is a usable candidate dataset rather than telemetry alone.
- `approval_outcome.py` — frozen dataclass with `workflow_run_id`, `draft_id`, `slack_user_id`, `email_id`, `thread_id`, `action: ResumeAction`, `user_intent: Literal["would_send", "save_draft", "would_reject"]`, `success`, `gmail_message_id`, `gmail_draft_id`, `error`, `timestamp`. In shadow mode, send intent receives a synthetic `shadow_msg_*` ID; a successful save carries the real Gmail draft ID; reject carries neither.
- `shadow_gmail_writer.py` — subclass of `GmailWriter`. Overrides `send_draft` and `send_reply`; inherits `save_draft`.

Touched code:

- `src/workflows/factory.py` — mode-aware wiring.
- `src/slack_handlers/draft_approval_handler.py` — return `ApprovalOutcome`; accept `app_mode` and use it to choose the Send button label; stash `email_id` and `thread_id` in `pending_drafts[draft_id]` so the outcome can carry them.
- `src/routes/integrations_slack/slack_routes.py` — call `recorder.record_approval_outcome(outcome)` between the handler call and `resume_workflow_after_action(...)`.
- `src/workflows/workflow.py` — emit `workflow_started`, `email_ingested` (per email), `draft_candidate_recorded` (input/context plus generated body), `draft_surfaced` (after `chat_postMessage` success), `workflow_completed`.
- `src/agent/agent.py` — `set_context(**kwargs)` / `clear_context()` plus `record_llm_call` emit inside `_timed_completion`.
- `src/utils/usage_tracker.py` — `log_usage` accepts optional `workflow_run_id`, `stage`, `draft_id` (backward-compatible defaults).
- `.env.example` — `INBOX0_SHADOW_MODE=false` with comment.
- `metrics/.gitignore` — ignore `*.jsonl`.

---

## Slack button copy

The two actions shadow mode intercepts use `Would …` framing. Saving keeps its live label because it creates a real Gmail draft.

| Action  | Live label           | Shadow label        |
|---------|----------------------|---------------------|
| approve | ✅ Approve & Send    | 👻 Would Send       |
| save    | 💾 Save Draft        | 💾 Save Draft       |
| reject  | ❌ Reject            | 👻 Would Reject     |

`action_id` and `value` strings are identical in both modes so the route dispatch and `ResumeAction` mapping are unchanged.

The labels state the consequence accurately: `Would Send` and `Would Reject` record intent, while `Save Draft` performs a real, non-sending Gmail write. Self-reported edit magnitude (a follow-up "minor / major edits" prompt) was considered and dropped — see Limitations.

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
├── events.jsonl       # MetricRecorder events
└── llm_calls.jsonl    # extended UsageTracker (now includes workflow_run_id, stage, draft_id)
```

Two files, both append-only JSONL, both joined offline by `workflow_run_id` and `draft_id`. The duplication between `llm_calls.jsonl` and `events.jsonl[event=llm_call_completed]` is intentional in this PR: `usage_tracker.json` already exists and other code reads it; one of the two will get collapsed in a follow-on cleanup once nothing else depends on the old shape.

---

## What this PR does not include

These are deferred to follow-on PRs and tracked separately so this collection layer can ship small:

- Offline reporter that reads `events.jsonl` and prints send-rate / latency p50,p95 / cost per draft.
- Edit-distance gates (token Levenshtein, semantic cosine) from 001.
- LLM-judge threshold calibration loop from 001.
- Pricing table for cost-per-draft math.
- File rotation policy for `metrics/*.jsonl`.
- Migration of `UsageTracker` callers onto `MetricRecorder`.

---

## Limitations: shadow mode is a cold-start instrument, not the harness

First, what shadow mode earns outright: **a candidate evaluation dataset plus latency and cost per draft.** The candidate record contains the pipeline input/context, generated output, and user action. Latency and cost are read from the real pipeline executing — per-stage token counts and wall-clock from ingest to draft-surfaced — and neither depends on whether a send happens.

The limitation is the third. The send rate (and the edit distance folded into it) in [001](001-gold_metrics.md) is defined as an **outcome** signal: was the email *sent*, how much did the user *change* it before sending. Shadow mode, by design, intercepts the consequence. So it can only ever collect **intent** — a `Would Send` click, not a sent email. That gap is real and worth stating plainly:

- **Intent overestimates send rate, but in a known direction.** Clicking `Would Send` costs nothing. Under zero stakes the user rubber-stamps drafts that are merely "good enough" — ones they would tighten or kill if the email were actually going out under their name. This low-stakes bias is systematic and *optimistic*: it inflates the rate rather than scrambling it. That directionality is what makes the signal salvageable — shadow-mode send rate is an upper bound now, and once the [003 harness](003-eval_harness.md) produces real sends, the gap between `Would Send` rate and true send rate can be estimated and shadow data carried forward as a debiased estimator rather than discarded.
- **Edit distance is deferred, not discarded.** `Would Send` produces no sent body and therefore no drafted-vs-sent pair. `Save Draft`, however, retains the generated body, thread ID, and real Gmail draft ID. A later folder observer can use those fields to recover an edited or sent body. Building that observer and computing the diff belong to the [003 harness](003-eval_harness.md), not this collection layer.
- **The "Save-then-what" branches remain unscored here.** 001's rubric forks on downstream behavior (saved → sent as-is = pass; saved → never sent but manual reply = fail/drafter). Shadow mode creates the draft and preserves the join keys, but deliberately does not poll Gmail or classify the downstream outcome.

A consequence worth recording for the button design: self-reported edit magnitude (e.g. a follow-up "minor edits / major edits" prompt) was considered and rejected. A prospective, subjective self-report is a noisy proxy for a number the 003 harness can compute precisely from drafted-vs-sent diffs. Shadow mode keeps three plain buttons (`Would Send`, `Save Draft`, `Would Reject`), records intent for the shadowed actions and a real draft ID for saves, and defers all edit-magnitude measurement to the harness.

**One conflation to avoid.** Shadow examples are candidate examples, not automatically gold examples. A `Would Send` click is an intent label, not a sent outcome. The first ~50 examples used by 001 to calibrate edit-distance thresholds must still be drafted-vs-sent pairs. Saved shadow drafts can later contribute such pairs if a folder observer captures their final sent bodies, but merely creating the draft does not clear the calibration bar.

The conclusion: shadow mode is a **safe candidate-dataset bootstrap with no outbound-email risk.** It captures real pipeline inputs and outputs, user intent, latency, and cost. An explicit save creates a useful Gmail draft and preserves the linkage needed for future drafted-vs-sent measurement, but shadow mode does not perform that measurement itself. Behavioral ground truth remains the responsibility of [003-eval_harness.md](003-eval_harness.md).

---

## Relationship to other ADRs

- [evaluation/001-gold_metrics.md](001-gold_metrics.md) — defines what gets measured. This ADR builds the collection surface that makes those measurements computable. The `Capture surface` table in 001 maps cleanly onto the events emitted here.
- [evaluation/003-eval_harness.md](003-eval_harness.md) — the actual evaluation engine. Shadow mode is the cold-start bootstrap that seeds it; 003 owns the deterministic replay and live-observation paths that produce the outcome-defined gold metrics shadow mode cannot.
- [reliability/001-idempotent-write-side-retry-strategy-for-mail-and-slack.md](../reliability/001-idempotent-write-side-retry-strategy-for-mail-and-slack.md) — `MetricRecorder.record` must be side-effect-isolated and safely repeatable; this ADR honors that by writing to JSONL and avoiding any cross-event state.

---

## Open questions

1. ~~Should all three buttons say `Would …` in shadow mode?~~ **Resolved:** no. `Would Send` and `Would Reject` are intent-only. `Save Draft` keeps its live label and creates a real Gmail draft.
2. Should `email_ingested` events fire per-email or per-batch with a list? Per-email is simpler to join; per-batch is cheaper at high volume. Default: per-email until volume forces a change.
3. When `INBOX0_SHADOW_MODE` is unset, do we still construct a `MetricRecorder` and emit events (so the harness can backfill from live data later), or skip emission entirely? Default proposed: still construct, still emit. The recorder is cheap and the parallelism is the whole point.

---

## Decision

Implement shadow mode as a five-module evaluation layer under `src/eval/` plus a small number of returning-an-outcome changes to existing handlers. The flag is `INBOX0_SHADOW_MODE`, defaults off. When on, outbound Gmail writes (`send_draft` and `send_reply`) become no-ops; `Save Draft` remains live and returns a real Gmail draft ID. The collection layer durably records the pipeline input/context, generated body, user action, join keys, latency, and token usage. Everything else — drafts generated, drafts shown for review, LLM calls made — runs the live code path so the candidate dataset reflects the live system. Downstream Gmail polling, edit distance, and true send-rate computation remain explicitly out of scope and belong to the [003 harness](003-eval_harness.md).
