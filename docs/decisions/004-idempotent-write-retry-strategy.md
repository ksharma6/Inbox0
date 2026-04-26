# 004 — Idempotent Write-Side Retry Strategy for Gmail and Slack

**Status:** Proposed  
**Date:** 2026-04-25  

---

## Context

Inbox0 now retries transient failures for operations that are relatively safe to repeat: LLM calls and Gmail read calls. Those retries improve reliability because a failed read or generation call usually has no external side effect.

The remaining reliability gap is write-side behavior:

- creating Gmail drafts
- sending Gmail replies
- sending Slack approval messages
- applying Slack/Flask approval, reject, and save actions

These operations are not naturally idempotent. If the API call succeeds but Inbox0 times out before receiving the response, a naive retry can duplicate the side effect:

- `create_draft()` succeeds, response times out, retry creates a duplicate draft.
- `send_reply()` succeeds, response times out, retry sends the same email twice.
- Slack delivers the same action twice, and `current_draft_index` advances twice.
- A user chooses `save_draft`, but a replayed workflow action is treated like an approval.

For this reason, Inbox0 should not add automatic retries to GmailWriter or Slack write/action handlers until it has an idempotency strategy.

---

## Goal

Design and evaluate a write-side reliability strategy that can recover from transient failures without creating duplicate emails, duplicate drafts, or incorrect approval state transitions.

The first implementation should be experimental. The output should be a measured recommendation, not an immediate production retry wrapper around every write method.

---

## Relationship to ADR 003

ADR 003 proposes building an email classification dataset to decide whether a lightweight classifier can replace some LLM response-required decisions.

This ADR should reuse that dataset work instead of creating a separate corpus from scratch. The same `EmailMessage` fixtures can support both efforts if they include enough metadata:

```python
from dataclasses import dataclass
from src.models.gmail import EmailMessage


@dataclass
class EmailScenario:
    email: EmailMessage
    category: str
    draft_warranted: bool
    thread_depth: int
    expected_recipient: str
    expected_subject: str
```

ADR 003 cares about whether a draft is warranted. This ADR cares about what happens after a draft or user action is attempted. The overlap is the email/thread fixture itself.

Recommended shared fixture layout:

```text
tests/
  fixtures/
    email_scenarios.py
```

Then ADR-specific wrappers can extend the same base scenarios:

```python
@dataclass
class ClassificationCase:
    scenario: EmailScenario
    draft_warranted: bool


@dataclass
class WriteReliabilityCase:
    scenario: EmailScenario
    failure_mode: str
    expected_recovery: str
```

This keeps the dataset effort focused: generate and maintain one representative set of email/thread scenarios, then use it for multiple evaluations.

---

## Experiment Dataset

Start with roughly 30 scenarios. The goal is not statistical confidence; it is to expose failure modes early before designing production retries.

The dataset should include:

| Scenario type | Why it matters |
|---|---|
| Single-message direct ask | Simplest happy path for draft creation |
| Multi-message thread | Thread IDs must disambiguate similar replies |
| Same subject, different sender | Subject-only matching would false-positive |
| Same sender, repeated subject | Recipient/sender alone is insufficient |
| Very short draft body | Body hashes may collide more easily after normalization |
| Long draft body | Tests body hashing and Gmail search practicality |
| Similar generated drafts | Detects overly broad duplicate matching |
| Approval action | Should advance exactly once |
| Reject action | Should advance exactly once without sending |
| Save action | Should preserve draft without treating it as approved |
| Delayed Gmail consistency | Draft/Sent search may not show the side effect immediately |

The 30-scenario dataset can be synthetic at first. Use the ADR 003 category distribution as a base, then annotate scenarios with write-side expectations.

---

## Failure Modes to Simulate

Use mocked Gmail and Slack clients first. Real API fault injection is unnecessary for the first pass.

Simulate:

1. **Request failed before provider accepted it**
   - Safe to retry if the operation did not happen.

2. **Provider completed the operation but response timed out**
   - Dangerous case. Retry may duplicate the side effect.

3. **Provider returned `429` or `5xx`**
   - May or may not have applied the operation depending on endpoint behavior.

4. **Gmail Drafts/Sent search is eventually consistent**
   - The matching draft or sent message appears only after a short delay.

5. **Slack action delivered twice**
   - Approval/save/reject should be applied once.

6. **Workflow process restarts after writing but before saving local state**
   - Local state may not know the side effect happened.

---

## Candidate Strategies

### 1. Draft Lookup Before Retry

For `GmailWriter.create_draft()`:

1. Compute an operation fingerprint before calling Gmail:
   - recipient
   - normalized subject
   - Gmail thread ID
   - normalized body hash
2. Attempt draft creation.
3. If the request times out, wait briefly.
4. Search Gmail Drafts for a matching draft.
5. If a match exists, treat the operation as successful.
6. If no match exists, retry draft creation once.

This is the most promising write-side retry candidate. Duplicate drafts are still bad, but less harmful than duplicate sent emails.

### 2. Sent Mail Verification Before Send Retry

For `send_reply()` or other send operations:

1. Compute the same operation fingerprint before sending.
2. Attempt send.
3. If the request times out, wait briefly.
4. Search Sent Mail for a matching sent email.
5. If a match exists, treat the operation as successful.
6. If no match exists, report an uncertain send state.

Do not automatically retry sends unless Inbox0 can prove the first send did not happen. Duplicate sent emails are user-visible and should be treated as a severe failure.

### 3. Workflow Action Ledger

For Slack and Flask approval actions:

1. Generate or extract an action ID for each approval/save/reject event.
2. Store the action ID before applying the state transition.
3. Before applying an action, check whether the action ID has already been processed.
4. If already processed, acknowledge but do not advance workflow state again.

This protects `current_draft_index` from double-incrementing when Slack retries or delivers duplicate actions.

### 4. Separate Draft Creation From Sending

Keep workflow states explicit:

```text
draft_generated
draft_created
awaiting_user_approval
user_approved
send_attempted
send_confirmed
send_uncertain
```

This makes it easier to recover because Inbox0 knows which stage is safe to retry and which stage needs verification.

### 5. Provider Idempotency Keys

Investigate whether Gmail or Slack supports request-level idempotency keys for the specific operations Inbox0 uses.

If the provider supports idempotency keys, use them. If not, Inbox0 needs application-level idempotency using fingerprints, state records, and verification queries.

---

## Metrics

Measure each candidate strategy against the same 30 scenarios.

Primary safety metrics:

- duplicate sent emails
- duplicate drafts
- incorrect approval/save/reject transitions
- false positives when matching an existing draft or sent email
- false negatives when failing to detect an already-created draft or sent email
- uncertain send states surfaced to the user

Operational metrics:

- added latency after a timeout
- number of Gmail search calls added
- implementation complexity
- clarity of user-facing error messages

Suggested success criteria:

- `0` duplicate sent emails
- `0` incorrect approval/save/reject state transitions
- duplicate drafts either eliminated or detected
- uncertain send states are reported instead of retried blindly
- timeout recovery adds no more than 10-15 seconds in the common case

---

## Proposed Experiment Harness

Create a small experiment module rather than shipping production behavior immediately:

```text
tests/
  evals/
    test_write_idempotency.py
  fixtures/
    email_scenarios.py
```

The eval should run against mocked Gmail and Slack clients. Each case should define:

- input email/thread scenario
- operation attempted
- simulated failure mode
- provider-side side effect, if any
- expected recovery behavior

Example:

```python
WriteReliabilityCase(
    scenario=direct_question_thread,
    operation="create_draft",
    failure_mode="success_then_timeout",
    expected_recovery="find_existing_draft",
)
```

These tests can run in normal CI if fully mocked. If later experiments call real Gmail APIs, mark them separately as `@pytest.mark.eval` and keep them out of default CI.

---

## Decision Guidance

Recommended near-term decision:

1. Do not add Tenacity retries to GmailWriter or Slack send/action methods yet.
2. Add read/LLM retries only, which are already safe and implemented separately.
3. Build a mocked idempotency experiment using the shared ADR 003 email scenarios.
4. Implement the lowest-risk write-side protection first:
   - workflow action ledger for approval/save/reject
   - draft lookup before retry for draft creation
5. Keep email send retry conservative:
   - verify Sent Mail first
   - if verification is inconclusive, surface an uncertain send state instead of retrying blindly

---

## Open Questions

1. Can Gmail Drafts and Sent Mail search reliably find messages quickly enough after creation/send, or is there too much consistency delay?
2. What exact body normalization should be used before hashing?
3. Should operation fingerprints be stored in workflow state, Gmail draft metadata, or a separate local action ledger?
4. How long should Inbox0 wait before checking Drafts/Sent after a timeout?
5. Should duplicate draft detection be allowed to auto-recover, while duplicate send uncertainty requires user confirmation?
6. Should Slack action IDs be derived from Slack payload fields or generated by Inbox0 when the approval message is created?

---

## Next Steps

1. Extract or create shared email scenarios for ADR 003 and this ADR.
2. Add 30 synthetic email/thread scenarios covering classification and write-side failure cases.
3. Implement mocked tests for draft lookup, sent-mail verification, and duplicate Slack action delivery.
4. Record latency and mistake counts for each candidate strategy.
5. Decide which write-side safeguards should be implemented before adding any retries to GmailWriter or Slack action handling.
