from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

from src.routes.web.schemas import ResumeAction

UserIntent = Literal["would_send", "save_draft", "would_reject"]

# Capture user button click on Slack UI.
_INTENT_BY_ACTION: dict[ResumeAction, UserIntent] = {
    ResumeAction.APPROVE_DRAFT: "would_send",
    ResumeAction.SAVE_DRAFT: "save_draft",
    ResumeAction.REJECT_DRAFT: "would_reject",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class HumanDecision:
    """Captures a user's Slack decision for an agent-proposed draft.

    Records the user's intent, the outcome of the action, and the identifiers
    needed to associate the decision with its workflow, email, and draft.
    """

    workflow_run_id: str
    draft_id: str
    slack_user_id: str
    email_id: str
    thread_id: str
    action: ResumeAction
    user_intent: UserIntent
    success: bool
    gmail_message_id: Optional[str] = None
    gmail_draft_id: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=_utc_now_iso)

    @classmethod
    def from_resume_action(
        cls,
        action: ResumeAction,
        *,
        workflow_run_id: str,
        draft_id: str,
        slack_user_id: str,
        email_id: str,
        thread_id: str,
        success: bool,
        gmail_message_id: Optional[str] = None,
        gmail_draft_id: Optional[str] = None,
        error: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> "HumanDecision":

        return cls(
            workflow_run_id=workflow_run_id,
            draft_id=draft_id,
            slack_user_id=slack_user_id,
            email_id=email_id,
            thread_id=thread_id,
            action=action,
            user_intent=_INTENT_BY_ACTION[action],
            success=success,
            gmail_message_id=gmail_message_id,
            gmail_draft_id=gmail_draft_id,
            error=error,
            timestamp=timestamp if timestamp is not None else _utc_now_iso(),
        )
