"""Domain-level metric event schemas for gold-metric evaluation collection.

These events form the input to the v1.0 evaluation harness described in
`docs/decisions/evaluation/001-gold_metrics.md`. They are intentionally
domain-shaped (one event per workflow step) rather than generic log records,
so downstream consumers can join by `workflow_run_id` and `draft_id` to
reconstruct a single Inbox0 run end-to-end.

Each event subclass declares a `Literal` `event_type` so a `TypeAdapter` over
the `MetricEvent` discriminated union can deserialize an arbitrary JSONL line
into the correct typed model.
"""

import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


SlackActionLiteral = Literal["approve", "save", "reject", "would_send"]
LlmStageLiteral = Literal["email_summary", "draft_triage", "draft_generation"]


class _BaseMetricEvent(BaseModel):
    """Fields shared by every metric event.

    `workflow_run_id` is the universal join key. The other identifiers are
    optional on the base because not every event has them at the point of
    emission (e.g. `workflow_started` fires before any email is observed).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime.datetime = Field(default_factory=_utcnow, description="UTC time the event occurred")
    workflow_run_id: str = Field(..., description="ID of the Inbox0 workflow run this event belongs to")
    gmail_account_id: Optional[str] = Field(default=None, description="Gmail account that owns the run")
    slack_user_id: Optional[str] = Field(default=None, description="Slack user reviewing drafts for the run")


class WorkflowStartedEvent(_BaseMetricEvent):
    event_type: Literal["workflow_started"] = "workflow_started"


class EmailObservedEvent(_BaseMetricEvent):
    event_type: Literal["email_observed"] = "email_observed"
    email_id: str = Field(..., description="Gmail message ID of the observed email")
    thread_id: str = Field(..., description="Gmail thread ID the email belongs to")


class DraftGeneratedEvent(_BaseMetricEvent):
    event_type: Literal["draft_generated"] = "draft_generated"
    draft_id: str = Field(..., description="Inbox0-generated ID for this draft candidate")
    email_id: str = Field(..., description="Gmail message ID of the source email")
    thread_id: str = Field(..., description="Gmail thread ID of the source email")


class SlackDraftPresentedEvent(_BaseMetricEvent):
    event_type: Literal["slack_draft_presented"] = "slack_draft_presented"
    draft_id: str = Field(..., description="Inbox0 draft ID that was shown in Slack")


class SlackActionRecordedEvent(_BaseMetricEvent):
    event_type: Literal["slack_action_recorded"] = "slack_action_recorded"
    draft_id: str = Field(..., description="Inbox0 draft ID the user acted on")
    action: SlackActionLiteral = Field(..., description="User intent captured from the Slack button press")
    shadow_mode: bool = Field(..., description="Whether the run was in shadow mode when the action was taken")


class GmailDraftSavedEvent(_BaseMetricEvent):
    event_type: Literal["gmail_draft_saved"] = "gmail_draft_saved"
    draft_id: str = Field(..., description="Inbox0 draft ID that was persisted to Gmail Drafts")
    gmail_draft_id: Optional[str] = Field(default=None, description="Gmail-assigned ID of the saved draft, if returned")


class LlmUsageRecordedEvent(_BaseMetricEvent):
    event_type: Literal["llm_usage_recorded"] = "llm_usage_recorded"
    model: str = Field(..., description="Model identifier used for the call")
    prompt_tokens: int = Field(..., ge=0, description="Tokens consumed by the prompt")
    completion_tokens: int = Field(..., ge=0, description="Tokens produced in the completion")
    latency_ms: float = Field(..., ge=0.0, description="Wall-clock latency of the LLM call in milliseconds")
    stage: Optional[LlmStageLiteral] = Field(
        default=None,
        description="Pipeline stage that issued the call; None when called outside a tagged stage scope",
    )


class WorkflowCompletedEvent(_BaseMetricEvent):
    event_type: Literal["workflow_completed"] = "workflow_completed"
    final_status: str = Field(..., description="Final workflow status (e.g. completed, paused, error)")
    emails_observed: int = Field(..., ge=0, description="Count of emails observed during the run")
    drafts_generated: int = Field(..., ge=0, description="Count of drafts generated during the run")


MetricEvent = Annotated[
    Union[
        WorkflowStartedEvent,
        EmailObservedEvent,
        DraftGeneratedEvent,
        SlackDraftPresentedEvent,
        SlackActionRecordedEvent,
        GmailDraftSavedEvent,
        LlmUsageRecordedEvent,
        WorkflowCompletedEvent,
    ],
    Field(discriminator="event_type"),
]
