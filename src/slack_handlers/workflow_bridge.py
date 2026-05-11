"""Slack-side adapter that resumes a paused workflow after an approval action.

This module is the thin Slack-equivalent of Flask's /resume_workflow route: it
sources the bot's configured Gmail account ID for the ownership check, calls
EmailProcessingWorkflow.resume(...), and renders the typed WorkflowRunResult
as a Slack message via the ``respond`` callback. All orchestration (state
loading, action transitions, LangGraph streaming, persistence, ownership
enforcement) lives inside the workflow class.
"""

import logging
from os import getenv

from src.models.agent_schemas import WorkflowResultStatus
from src.routes.web.schemas import ResumeAction
from src.workflows.workflow import EmailProcessingWorkflow

logger = logging.getLogger(__name__)

GMAIL_ACCOUNT_ID_ENV = "INBOX0_GMAIL_ACCOUNT_ID"


def resume_workflow_after_action(
    workflow_run_id: str | None,
    action: ResumeAction,
    respond,
    workflow: EmailProcessingWorkflow,
) -> None:
    """Resume a paused workflow run triggered by a Slack approval action.

    Args:
        workflow_run_id: Workflow run ID parsed from the Slack action value.
            None means the payload was malformed; the user is warned and the
            workflow is not touched.
        action: The user's button choice (APPROVE_DRAFT, REJECT_DRAFT, or
            SAVE_DRAFT). Threaded through to workflow.resume(...) so reject and
            save are no longer silently treated as approve.
        respond: Slack ``respond`` callback used to send a status message back
            to the user.
        workflow: The shared EmailProcessingWorkflow instance.
    """
    if not workflow_run_id:
        logger.warning(
            "Slack resume action received without workflow_run_id",
            extra={"event": "slack_resume_missing_run_id", "action": action.value},
        )
        respond(":warning: Could not resume workflow: missing workflow run ID.")
        return

    gmail_account_id = getenv(GMAIL_ACCOUNT_ID_ENV)
    if not gmail_account_id:
        logger.error(
            "Slack resume blocked: %s is not set",
            GMAIL_ACCOUNT_ID_ENV,
            extra={
                "event": "slack_resume_server_not_configured",
                "workflow_run_id": workflow_run_id,
                "action": action.value,
            },
        )
        respond(":warning: Could not resume workflow: server is not configured.")
        return

    result = workflow.resume(workflow_run_id, gmail_account_id, action)

    if result.status is WorkflowResultStatus.NOT_FOUND:
        logger.warning(
            "Slack resume requested for unknown workflow_run_id=%s",
            workflow_run_id,
            extra={
                "event": "slack_resume_state_not_found",
                "workflow_run_id": workflow_run_id,
                "action": action.value,
            },
        )
        respond(":warning: Could not resume workflow: saved state was not found.")
        return
    if result.status is WorkflowResultStatus.FORBIDDEN:
        logger.warning(
            "Slack resume forbidden: workflow_run_id=%s does not belong to configured gmail_account_id",
            workflow_run_id,
            extra={
                "event": "slack_resume_forbidden",
                "workflow_run_id": workflow_run_id,
                "configured_gmail_account_id": gmail_account_id,
                "action": action.value,
            },
        )
        respond(":warning: Could not resume workflow: this run is owned by a different Gmail account.")
        return
    if result.status is WorkflowResultStatus.PAUSED:
        logger.info(
            "Slack resume paused at next draft: workflow_run_id=%s",
            workflow_run_id,
            extra={
                "event": "slack_resume_paused",
                "workflow_run_id": workflow_run_id,
                "action": action.value,
            },
        )
        respond("⏸️ Workflow paused. Waiting for next draft approval.")
        return
    if result.workflow_complete:
        logger.info(
            "Slack resume completed workflow: workflow_run_id=%s",
            workflow_run_id,
            extra={
                "event": "slack_resume_workflow_complete",
                "workflow_run_id": workflow_run_id,
                "action": action.value,
            },
        )
        respond("✅ Workflow completed successfully!")
    else:
        logger.info(
            "Slack resume stream ended without workflow_complete flag: workflow_run_id=%s",
            workflow_run_id,
            extra={
                "event": "slack_resume_completed_partial",
                "workflow_run_id": workflow_run_id,
                "action": action.value,
            },
        )
        respond("✅ Workflow resumed and completed.")
