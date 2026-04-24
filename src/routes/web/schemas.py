from enum import Enum

from pydantic import BaseModel, Field

SLACK_USER_ID_PATTERN = r"^U[A-Z0-9]{8,}$"
SLACK_USER_ID_DESCRIPTION = "Slack user ID (e.g. U090QS5DDEE)"


class ResumeAction(str, Enum):
    """Allowed actions when resuming a paused workflow."""

    APPROVE_DRAFT = "approve_draft"
    REJECT_DRAFT = "reject_draft"
    SAVE_DRAFT = "save_draft"


class StartWorkflowRequest(BaseModel):
    """Request body for POST /start_workflow."""

    user_id: str = Field(
        ...,
        pattern=SLACK_USER_ID_PATTERN,
        description=SLACK_USER_ID_DESCRIPTION,
    )


class ResumeWorkflowRequest(BaseModel):
    """Request body for POST /resume_workflow."""

    user_id: str = Field(
        ...,
        pattern=SLACK_USER_ID_PATTERN,
        description=SLACK_USER_ID_DESCRIPTION,
    )
    action: ResumeAction = Field(..., description="Action to take on the current draft")
