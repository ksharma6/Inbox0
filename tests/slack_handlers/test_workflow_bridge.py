"""Tests for the Slack workflow bridge after centralization (issue #80).

The bridge is now a thin Slack adapter around EmailProcessingWorkflow.resume():
- sources the server's configured INBOX0_GMAIL_ACCOUNT_ID for the ownership check
- delegates orchestration to workflow.resume(workflow_run_id, gmail_account_id, action)
- translates the typed WorkflowRunResult into a Slack `respond` message
- emits structured `event=slack_resume_*` log lines for operator traceability

These tests cover every result-status branch and add a regression guard for the
prior bug where the bridge silently treated every action as approve. caplog
assertions are limited to the two security/operator-critical log paths
(FORBIDDEN, server-not-configured); happy-path INFO logs are not asserted on
to keep the suite from being brittle to log-message wording.
"""

import logging
from unittest.mock import patch

from src.models.agent_schemas import WorkflowResultStatus, WorkflowRunResult
from src.routes.web.schemas import ResumeAction
from src.slack_handlers import workflow_bridge

GMAIL_ACCOUNT_ID = "gmail-account-123"
WORKFLOW_RUN_ID = "workflow-run-123"
SERVER_CONFIGURED_ENV = {"INBOX0_GMAIL_ACCOUNT_ID": GMAIL_ACCOUNT_ID}


def test_warns_when_workflow_run_id_missing(mocker):
    """No workflow_run_id means the Slack action payload was malformed;
    do not call workflow.resume() and warn the user."""
    respond = mocker.Mock()
    workflow = mocker.Mock()

    workflow_bridge.resume_workflow_after_action(None, ResumeAction.APPROVE_DRAFT, respond, workflow)

    workflow.resume.assert_not_called()
    respond.assert_called_once_with(":warning: Could not resume workflow: missing workflow run ID.")


def test_warns_when_server_not_configured(mocker, caplog):
    """Missing INBOX0_GMAIL_ACCOUNT_ID is a server-side config error;
    the bridge must not call workflow.resume() and must log at ERROR so
    operators can spot the misconfiguration."""
    respond = mocker.Mock()
    workflow = mocker.Mock()

    with patch.dict("os.environ", {}, clear=True), caplog.at_level(logging.ERROR):
        workflow_bridge.resume_workflow_after_action(WORKFLOW_RUN_ID, ResumeAction.APPROVE_DRAFT, respond, workflow)

    workflow.resume.assert_not_called()
    respond.assert_called_once_with(":warning: Could not resume workflow: server is not configured.")

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1
    assert getattr(error_records[0], "event") == "slack_resume_server_not_configured"
    assert getattr(error_records[0], "workflow_run_id") == WORKFLOW_RUN_ID


def test_warns_when_workflow_resume_returns_not_found(mocker):
    """NOT_FOUND result from workflow.resume() (saved state missing or expired)
    translates to a user-facing warning; the bridge does not retry or re-load."""
    respond = mocker.Mock()
    workflow = mocker.Mock()
    workflow.resume.return_value = WorkflowRunResult(
        status=WorkflowResultStatus.NOT_FOUND,
        workflow_run_id=WORKFLOW_RUN_ID,
        error_message=f"No saved workflow state found for workflow_run_id={WORKFLOW_RUN_ID}",
    )

    with patch.dict("os.environ", SERVER_CONFIGURED_ENV):
        workflow_bridge.resume_workflow_after_action(WORKFLOW_RUN_ID, ResumeAction.APPROVE_DRAFT, respond, workflow)

    respond.assert_called_once_with(":warning: Could not resume workflow: saved state was not found.")


def test_warns_when_workflow_resume_returns_forbidden(mocker, caplog):
    """FORBIDDEN result means the saved state's gmail_account_id does not
    match the server's configured account. This is a potential cross-account
    resume attempt and must be logged at WARNING with the structured
    `slack_resume_forbidden` event so it shows up in security audits."""
    respond = mocker.Mock()
    workflow = mocker.Mock()
    workflow.resume.return_value = WorkflowRunResult(
        status=WorkflowResultStatus.FORBIDDEN,
        workflow_run_id=WORKFLOW_RUN_ID,
        error_message="Workflow run is owned by a different gmail_account_id",
    )

    with patch.dict("os.environ", SERVER_CONFIGURED_ENV), caplog.at_level(logging.WARNING):
        workflow_bridge.resume_workflow_after_action(WORKFLOW_RUN_ID, ResumeAction.APPROVE_DRAFT, respond, workflow)

    respond.assert_called_once_with(
        ":warning: Could not resume workflow: this run is owned by a different Gmail account."
    )

    forbidden_records = [r for r in caplog.records if getattr(r, "event", None) == "slack_resume_forbidden"]
    assert len(forbidden_records) == 1
    assert forbidden_records[0].levelname == "WARNING"
    assert getattr(forbidden_records[0], "workflow_run_id") == WORKFLOW_RUN_ID


def test_responds_with_paused_message_when_workflow_pauses_again(mocker):
    """PAUSED result means the workflow has another draft awaiting approval;
    the user is told the workflow is still in flight."""
    respond = mocker.Mock()
    workflow = mocker.Mock()
    workflow.resume.return_value = WorkflowRunResult(
        status=WorkflowResultStatus.PAUSED,
        workflow_run_id=WORKFLOW_RUN_ID,
        awaiting_approval=True,
    )

    with patch.dict("os.environ", SERVER_CONFIGURED_ENV):
        workflow_bridge.resume_workflow_after_action(WORKFLOW_RUN_ID, ResumeAction.APPROVE_DRAFT, respond, workflow)

    respond.assert_called_once_with("⏸️ Workflow paused. Waiting for next draft approval.")


def test_responds_with_completed_message_when_workflow_completes(mocker):
    """COMPLETED + workflow_complete=True means the workflow ran to the
    final summary node and is fully done."""
    respond = mocker.Mock()
    workflow = mocker.Mock()
    workflow.resume.return_value = WorkflowRunResult(
        status=WorkflowResultStatus.COMPLETED,
        workflow_run_id=WORKFLOW_RUN_ID,
        workflow_complete=True,
    )

    with patch.dict("os.environ", SERVER_CONFIGURED_ENV):
        workflow_bridge.resume_workflow_after_action(WORKFLOW_RUN_ID, ResumeAction.APPROVE_DRAFT, respond, workflow)

    respond.assert_called_once_with("✅ Workflow completed successfully!")


def test_responds_with_resumed_message_on_partial_completion(mocker):
    """COMPLETED + workflow_complete=False is an edge case: the LangGraph
    stream exhausted but the workflow_complete flag never flipped. The user
    still sees a success message but the bridge logs the partial state."""
    respond = mocker.Mock()
    workflow = mocker.Mock()
    workflow.resume.return_value = WorkflowRunResult(
        status=WorkflowResultStatus.COMPLETED,
        workflow_run_id=WORKFLOW_RUN_ID,
        workflow_complete=False,
    )

    with patch.dict("os.environ", SERVER_CONFIGURED_ENV):
        workflow_bridge.resume_workflow_after_action(WORKFLOW_RUN_ID, ResumeAction.APPROVE_DRAFT, respond, workflow)

    respond.assert_called_once_with("✅ Workflow resumed and completed.")


def test_passes_action_type_to_workflow_resume(mocker):
    """Regression guard for the prior bug where the bridge silently treated
    every Slack button click as approve. The action MUST be forwarded to
    workflow.resume() so reject and save advance state through their own
    dispatch in _apply_resume_action."""
    respond = mocker.Mock()
    workflow = mocker.Mock()
    workflow.resume.return_value = WorkflowRunResult(
        status=WorkflowResultStatus.COMPLETED,
        workflow_run_id=WORKFLOW_RUN_ID,
        workflow_complete=True,
    )

    with patch.dict("os.environ", SERVER_CONFIGURED_ENV):
        workflow_bridge.resume_workflow_after_action(WORKFLOW_RUN_ID, ResumeAction.REJECT_DRAFT, respond, workflow)

    workflow.resume.assert_called_once_with(
        WORKFLOW_RUN_ID,
        GMAIL_ACCOUNT_ID,
        ResumeAction.REJECT_DRAFT,
    )
