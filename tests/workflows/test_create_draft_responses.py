from unittest.mock import patch

import pytest
from src.agent.agent import Agent
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
from src.models.agent_schemas import GmailAgentState
from src.models.gmail import EmailMessage
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler
from src.workflows.workflow import EmailProcessingWorkflow


@pytest.fixture
def workflow(mocker):
    """EmailProcessingWorkflow with all external dependencies mocked out."""
    gmail_reader = mocker.Mock(spec=GmailReader)
    gmail_writer = mocker.Mock(spec=GmailWriter)
    draft_handler = mocker.Mock(spec=DraftApprovalHandler)
    agent = mocker.Mock(spec=Agent)

    with patch("openai.OpenAI"):
        wf = EmailProcessingWorkflow(
            gmail_reader=gmail_reader,
            gmail_writer=gmail_writer,
            draft_handler=draft_handler,
            agent=agent,
        )
    return wf


def test_create_draft_responses_passes_original_thread_id(workflow, mocker):
    """Workflow-created Gmail drafts must retain the original email thread_id."""
    email = EmailMessage(
        id="email-1",
        subject="Meeting tomorrow",
        from_email="them@example.com",
        to_email="me@example.com",
        date="Sat, 09 May 2026 18:00:00 -0700",
        body="Can we still meet tomorrow?",
        thread_id="thread-123",
    )
    state = GmailAgentState(
        gmail_account_id="gmail-account-123",
        slack_user_id="U12345678",
        workflow_run_id="workflow-123",
        unread_emails=[email],
        processed_emails=[
            {
                "email_id": email.id,
                "priority": "High",
                "response_type": "Reply",
                "reason": "Needs confirmation",
            }
        ],
    )
    mocker.patch.object(workflow, "_generate_draft_response", return_value="Yes, see you then.")
    workflow.gmail_writer.create_draft.return_value = {"raw": "encoded-message", "threadId": email.thread_id}

    result = workflow._create_draft_responses(state)

    workflow.gmail_writer.create_draft.assert_called_once_with(
        sender=email.to_email,
        recipient=email.from_email,
        subject=f"Re: {email.subject}",
        message="Yes, see you then.",
        thread_id=email.thread_id,
    )
    assert result.draft_responses[0]["draft"]["threadId"] == email.thread_id


def test_hallucinated_slack_user_id_does_not_change_draft_routing(workflow, mocker):
    """LLM-derived draft metadata must not override the authenticated Slack route."""
    save_state = mocker.patch("src.workflows.workflow.save_state_to_store")
    workflow.draft_handler.send_draft_for_approval.return_value = "draft-123"
    state = GmailAgentState(
        gmail_account_id="gmail-account-123",
        slack_user_id="U12345678",
        workflow_run_id="workflow-123",
        draft_responses=[
            {
                "email_id": "email-1",
                "draft": {"raw": "encoded-message"},
                "priority": "High",
                "draft_content": "Looks good.",
                "slack_user_id": "UATTACKER1",
            }
        ],
    )

    result = workflow._send_drafts_to_slack(state)

    workflow.draft_handler.send_draft_for_approval.assert_called_once_with(
        draft={"raw": "encoded-message"},
        slack_user_id="U12345678",
        workflow_run_id="workflow-123",
    )
    assert result.awaiting_approval is True
    assert result.current_draft_id == "draft-123"
    save_state.assert_called_once_with(result)
