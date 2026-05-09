import logging
from datetime import datetime, timedelta

from src.slack_handlers.draft_approval_handler import DraftApprovalHandler


def test_draft_approval_handler_logging(caplog, mocker):
    """Test logging in draft approval handler"""

    slack_app = mocker.Mock()
    gmail_writer = mocker.Mock()
    say_mock = mocker.Mock()

    draft_handler = DraftApprovalHandler(gmail_writer=gmail_writer, slack_app=slack_app)

    draft_handler.pending_drafts["test_draft_id"] = {
        "draft": {"id": "draft_123"},
        "decoded_draft": {},
        "user_id": "test_user_id",
        "status": "pending",
        "slack_message_ts": "1234567890.123456",
        "slack_channel": "C12345",
    }
    with caplog.at_level(logging.INFO):
        draft_handler._handle_approve("test_draft_id", "test_user_id", say_mock)
        draft_handler._handle_reject("test_draft_id", "test_user_id", say_mock)
        draft_handler._handle_save("test_draft_id", "test_user_id", say_mock)

    assert "Draft approved - draft_id=test_draft_id user_id=test_user_id" in caplog.text
    assert "Draft rejected - draft_id=test_draft_id user_id=test_user_id" in caplog.text
    assert "Draft saved - draft_id=test_draft_id user_id=test_user_id" in caplog.text


def test_approval_message_button_values_include_workflow_run_id(mocker):
    slack_app = mocker.Mock()
    gmail_writer = mocker.Mock()
    draft_handler = DraftApprovalHandler(gmail_writer=gmail_writer, slack_app=slack_app)
    draft_handler.draft_timeouts["draft-abc-123"] = datetime.now() + timedelta(hours=1)

    message = draft_handler._create_approval_message(
        decoded_draft={},
        draft_id="draft-abc-123",
        workflow_run_id="workflow-run-123",
    )

    buttons = message["blocks"][1]["elements"]
    assert [button["value"] for button in buttons] == [
        "approve:workflow-run-123:draft-abc-123",
        "reject:workflow-run-123:draft-abc-123",
        "save:workflow-run-123:draft-abc-123",
    ]
