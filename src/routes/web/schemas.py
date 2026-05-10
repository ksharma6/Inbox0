from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

SLACK_USER_ID_PATTERN = r"^U[A-Z0-9]{8,}$"
SLACK_USER_ID_DESCRIPTION = "Slack user ID (e.g. U12345678)"


class ResumeAction(str, Enum):
    """Allowed actions when resuming a paused workflow."""

    APPROVE_DRAFT = "approve_draft"
    REJECT_DRAFT = "reject_draft"
    SAVE_DRAFT = "save_draft"


class StartWorkflowRequest(BaseModel):
    """Request body for POST /start_workflow."""

    model_config = ConfigDict(extra="forbid")


class ResumeWorkflowRequest(BaseModel):
    """Request body for POST /resume_workflow."""

    model_config = ConfigDict(extra="forbid")

    workflow_run_id: str = Field(..., description="Workflow run ID returned by /start_workflow")
    action: ResumeAction = Field(..., description="Action to take on the current draft")
