from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator
from src.eval.human_decision import HumanDecision, UserIntent


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO8601 string.

    Returns:
        str: The current time in UTC formatted per ISO8601 (e.g.
            "2024-01-01T12:00:00+00:00").
    """
    return datetime.now(timezone.utc).isoformat()


class EventBase(BaseModel):
    """Base class for all metric event models.

    Instances are immutable (``frozen=True``) and reject unknown fields
    (``extra="forbid"``), so constructing an event with a misspelled field name
    raises a validation error.

    Attributes:
        workflow_run_id (str): Identifier of the workflow run the event belongs
            to.
        timestamp (str): ISO8601 UTC time the event occurred. Defaults to the
            time the event is created.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_run_id: str
    timestamp: str = Field(default_factory=_utc_now_iso)


class WorkflowStarted(EventBase):
    """Marks the beginning of a workflow run.

    Attributes:
        event (str): Constant identifier for this event type.
        monotonic_ns (Optional[int]): A ``time.perf_counter_ns()`` reading taken
            at the start of the run, paired with the matching WorkflowCompleted
            event to compute run duration. Defaults to None.
    """

    event: Literal["workflow_started"] = "workflow_started"
    monotonic_ns: Optional[int] = None


class EmailIngested(EventBase):
    """Records that a single email was read from the inbox.

    Attributes:
        event (str): Constant identifier for this event type.
        email_id (str): Identifier of the email that was read.
        thread_id (Optional[str]): Identifier of the thread the email belongs
            to. Defaults to None.
    """

    event: Literal["email_ingested"] = "email_ingested"
    email_id: str
    thread_id: Optional[str] = None


class DraftCandidateRecorded(EventBase):
    """Stores the input and output of a generated draft.

    Attributes:
        event (str): Constant identifier for this event type.
        draft_id (str): Identifier of the generated draft.
        email_id (str): Identifier of the email the draft responds to.
        thread_id (Optional[str]): Identifier of the thread the email belongs
            to. Defaults to None.
        source_context (str): The message or thread text the draft was generated
            from.
        generated_body (str): The body text of the generated draft.
        generated_subject (Optional[str]): The subject line of the generated
            draft. Defaults to None.
        recipient (Optional[str]): The intended recipient of the draft. Defaults
            to None.
    """

    event: Literal["draft_candidate_recorded"] = "draft_candidate_recorded"
    draft_id: str
    email_id: str
    thread_id: Optional[str] = None
    source_context: str
    generated_body: str
    generated_subject: Optional[str] = None
    recipient: Optional[str] = None


class DraftSurfaced(EventBase):
    """Records that a generated draft was presented to the user for review.

    Attributes:
        event (str): Constant identifier for this event type.
        draft_id (str): Identifier of the presented draft.
        email_id (str): Identifier of the email the draft responds to.
        slack_message_ts (Optional[str]): Timestamp of the Slack message that
            presented the draft. Defaults to None.
    """

    event: Literal["draft_surfaced"] = "draft_surfaced"
    draft_id: str
    email_id: str
    slack_message_ts: Optional[str] = None


class HumanDecisionRecorded(EventBase):
    """Serializable record of a user's action on a proposed draft.

    Attributes:
        event (str): Constant identifier for this event type.
        draft_id (str): Identifier of the draft the user acted on.
        email_id (str): Identifier of the email the draft responds to.
        thread_id (str): Identifier of the thread the email belongs to.
        action (str): The action the user selected (e.g. "approve_draft",
            "save_draft", "reject_draft").
        user_intent (UserIntent): The interpreted intent of the action.
        success (bool): Whether the action completed successfully.
        gmail_message_id (Optional[str]): Identifier of the sent Gmail message,
            when a send occurred. Defaults to None.
        gmail_draft_id (Optional[str]): Identifier of the saved Gmail draft, when
            a save occurred. Defaults to None.
        error (Optional[str]): Error message describing why the action failed,
            when applicable. Defaults to None.
    """

    event: Literal["human_decision_recorded"] = "human_decision_recorded"
    draft_id: str
    email_id: str
    thread_id: str
    action: str
    user_intent: UserIntent
    success: bool
    gmail_message_id: Optional[str] = None
    gmail_draft_id: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def from_decision(cls, decision: HumanDecision) -> "HumanDecisionRecorded":
        """Create a HumanDecisionRecorded from a HumanDecision.

        Args:
            decision (HumanDecision): The decision whose fields are copied into
                the event.

        Returns:
            HumanDecisionRecorded: An event carrying the decision's fields, with
                the action's enum value stored as a string.
        """
        return cls(
            workflow_run_id=decision.workflow_run_id,
            timestamp=decision.timestamp,
            draft_id=decision.draft_id,
            email_id=decision.email_id,
            thread_id=decision.thread_id,
            action=decision.action.value,
            user_intent=decision.user_intent,
            success=decision.success,
            gmail_message_id=decision.gmail_message_id,
            gmail_draft_id=decision.gmail_draft_id,
            error=decision.error,
        )


class LLMCallCompleted(EventBase):
    """Records a single completed language-model call.

    Attributes:
        event (str): Constant identifier for this event type.
        model (str): Name of the model that produced the completion.
        prompt_tokens (int): Number of tokens in the prompt.
        completion_tokens (int): Number of tokens in the completion.
        total_tokens (Optional[int]): Sum of prompt and completion tokens.
            Defaults to prompt_tokens + completion_tokens when not supplied.
        stage (Optional[str]): Name of the workflow stage that made the call.
            Defaults to None.
        draft_id (Optional[str]): Identifier of the draft the call relates to.
            Defaults to None.
        duration_ns (Optional[int]): Elapsed ``time.perf_counter_ns()`` value for
            the call. Defaults to None.
    """

    event: Literal["llm_call_completed"] = "llm_call_completed"
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: Optional[int] = None
    stage: Optional[str] = None
    draft_id: Optional[str] = None
    duration_ns: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _fill_total_tokens(cls, data: Any) -> Any:
        """Populate total_tokens from the prompt and completion counts.

        Args:
            data (Any): Raw input to the model, typically a dict of field values.

        Returns:
            Any: The input unchanged, except that total_tokens is set to
                prompt_tokens + completion_tokens when it was omitted and both
                counts are present.
        """
        if isinstance(data, dict) and data.get("total_tokens") is None:
            prompt = data.get("prompt_tokens")
            completion = data.get("completion_tokens")
            if prompt is not None and completion is not None:
                data = {**data, "total_tokens": prompt + completion}
        return data


class EmailSendShadowed(EventBase):
    """Records that an outbound email send was intercepted and not sent.

    Attributes:
        event (str): Constant identifier for this event type.
        shadow_message_id (str): Placeholder identifier returned in place of a
            real sent-message id.
        send_path (Literal["send_draft", "send_reply"]): Which send operation was
            intercepted.
        draft_id (Optional[str]): Identifier of the draft whose send was
            suppressed. Defaults to None.
    """

    event: Literal["email_send_shadowed"] = "email_send_shadowed"
    shadow_message_id: str
    send_path: Literal["send_draft", "send_reply"]
    draft_id: Optional[str] = None


class WorkflowCompleted(EventBase):
    """Marks the end of a workflow run.

    Attributes:
        event (str): Constant identifier for this event type.
        monotonic_ns (Optional[int]): A ``time.perf_counter_ns()`` reading taken
            at the end of the run, paired with the matching WorkflowStarted event
            to compute run duration. Defaults to None.
        emails_processed (Optional[int]): Number of emails processed during the
            run. Defaults to None.
        drafts_created (Optional[int]): Number of drafts created during the run.
            Defaults to None.
    """

    event: Literal["workflow_completed"] = "workflow_completed"
    monotonic_ns: Optional[int] = None
    emails_processed: Optional[int] = None
    drafts_created: Optional[int] = None


MetricEvent = Union[
    WorkflowStarted,
    EmailIngested,
    DraftCandidateRecorded,
    DraftSurfaced,
    HumanDecisionRecorded,
    LLMCallCompleted,
    EmailSendShadowed,
    WorkflowCompleted,
]
