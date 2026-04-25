import datetime
import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
from src.models.gmail import EmailMessage, EmailSummary


def get_default_model():
    """Get the default model from environment or fallback to industry standard."""
    return os.getenv("OPENROUTER_MODEL", os.getenv("LLM_MODEL", "openai/gpt-4o-mini"))


def get_default_api_key():
    """Get the default API key from environment."""
    return os.getenv("OPENROUTER_API_KEY", os.getenv("OPENAI_API_KEY"))


def get_default_base_url():
    """Get the default base URL from environment or fallback to OpenRouter."""
    return os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


class AgentSchema(BaseModel):
    """Schema for agent configuration"""

    api_key: str = Field(
        default_factory=get_default_api_key,
        description="API key (OpenRouter or OpenAI)",
    )
    model: str = Field(
        default_factory=get_default_model,
        description="Model to use (e.g. openai/gpt-4o-mini)",
    )
    base_url: str = Field(default_factory=get_default_base_url, description="API Base URL")
    site_url: Optional[str] = Field(
        default=os.getenv("SITE_URL", "http://localhost:3000"),
        description="Site URL for OpenRouter rankings",
    )
    app_name: Optional[str] = Field(
        default=os.getenv("APP_NAME", "Inbox0"),
        description="App name for OpenRouter rankings",
    )
    available_tools: Dict[str, Any] = Field(default={}, description="Available tools for the agent")

    @field_validator("api_key", mode="before")
    @classmethod
    def api_key_must_be_set(cls, v: Any) -> str:
        if not v:
            raise ValueError("No API key found. Set OPENROUTER_API_KEY or OPENAI_API_KEY.")
        return v


class ProcessRequestSchema(BaseModel):
    """Schema for processing requests"""

    user_prompt: str = Field(..., description="User's request prompt")
    llm_tool_schema: Any = Field(..., description="Tool schema for LLM")
    system_message: Optional[str] = Field(default=None, description="System message for the agent")


class GmailAgentState(BaseModel):
    """State for Gmail processing workflow"""

    # Input
    user_id: str = Field(..., description="Slack user ID requesting email processing")
    thread_id: str = Field(..., description="Unique ID for the email processing thread")

    # Email data
    unread_emails: List[EmailMessage] = Field(default=[], description="List of unread emails")
    email_summary: Optional[EmailSummary] = Field(default=None, description="Summary of emails")

    # Processing state
    current_email_index: int = Field(default=0, description="Index of current email being processed")
    processed_emails: List[Dict] = Field(default=[], description="List of processed email results")

    # Draft responses
    draft_responses: List[Dict] = Field(default=[], description="List of draft responses created")
    pending_approvals: List[Dict] = Field(default=[], description="Drafts pending Slack approval")
    current_draft_index: int = Field(default=0, description="Index of the draft currently being reviewed")
    awaiting_approval: bool = Field(default=False, description="Whether waiting for Slack approval")
    awaiting_approval_since: Optional[datetime.datetime] = Field(
        default=None, description="Time when waiting for approval started"
    )
    current_draft_id: Optional[str] = Field(default=None, description="ID of the current draft being reviewed")

    # Workflow control
    should_continue: bool = Field(default=True, description="Whether to continue processing emails")
    error_message: Optional[str] = Field(default=None, description="Error message if any")

    # Final output
    final_summary: Optional[str] = Field(default=None, description="Final summary sent to user")
    workflow_complete: bool = Field(default=False, description="Whether workflow is complete")
