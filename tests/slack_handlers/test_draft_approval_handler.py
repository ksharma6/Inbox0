from datetime import datetime, timedelta

from src.eval.app_mode import AppMode
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler

DRAFT_ID = "draft-abc-123"
WORKFLOW_RUN_ID = "workflow-run-123"
MOCK_EMAIL = {
    "sender": "test sender",
    "recipient": "test recipient",
    "subject": "test subject",
    "body": "test body",
}


def test_gmail_writer_labels(mocker):
    """Verify that live mode shows the Approve & Send, Reject, and Save Draft labels."""

    slack_app = mocker.Mock()
    gmail_writer = mocker.Mock(app_mode=AppMode.LIVE)
    handler = DraftApprovalHandler(gmail_writer=gmail_writer, slack_app=slack_app)
    handler.draft_timeouts[DRAFT_ID] = datetime.now() + timedelta(hours=24)

    message = handler._create_approval_message(
        decoded_draft=MOCK_EMAIL,
        draft_id=DRAFT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
    )

    actions_block = message["blocks"][1]
    actions = [action["text"]["text"] for action in actions_block["elements"]]

    assert actions == ["✅ Approve & Send", "❌ Reject", "💾 Save Draft"]


def test_shadow_writer_labels(mocker):
    """Verify that shadow mode shows the Would Send, Would Reject, and Would Edit labels."""

    slack_app = mocker.Mock()
    shadow_writer = mocker.Mock(app_mode=AppMode.SHADOW)

    handler = DraftApprovalHandler(gmail_writer=shadow_writer, slack_app=slack_app)
    handler.draft_timeouts[DRAFT_ID] = datetime.now() + timedelta(hours=24)

    message = handler._create_approval_message(
        decoded_draft=MOCK_EMAIL,
        draft_id=DRAFT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
    )

    actions_block = message["blocks"][1]
    actions = [action["text"]["text"] for action in actions_block["elements"]]

    assert actions == ["👍 Would Send", "👎 Would Reject", "✏️ Would Edit"]


def test_routing_fields_match_across_mode(mocker):
    """Verify that button action IDs, values, and styles are identical in live and shadow mode."""

    slack_app = mocker.Mock()
    gmail_writer = mocker.Mock(app_mode=AppMode.LIVE)
    gmail_writer_handler = DraftApprovalHandler(gmail_writer=gmail_writer, slack_app=slack_app)
    gmail_writer_handler.draft_timeouts[DRAFT_ID] = datetime.now() + timedelta(hours=24)

    shadow_writer = mocker.Mock(app_mode=AppMode.SHADOW)
    shadow_writer_handler = DraftApprovalHandler(gmail_writer=shadow_writer, slack_app=slack_app)
    shadow_writer_handler.draft_timeouts[DRAFT_ID] = datetime.now() + timedelta(hours=24)

    live_message = gmail_writer_handler._create_approval_message(
        decoded_draft=MOCK_EMAIL,
        draft_id=DRAFT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
    )

    live_actions_blocks = live_message["blocks"][1]
    live_fields = [
        (button["action_id"], button["value"], button.get("style")) for button in live_actions_blocks["elements"]
    ]

    shadow_message = shadow_writer_handler._create_approval_message(
        decoded_draft=MOCK_EMAIL, draft_id=DRAFT_ID, workflow_run_id=WORKFLOW_RUN_ID
    )
    shadow_actions_blocks = shadow_message["blocks"][1]
    shadow_fields = [
        (button["action_id"], button["value"], button.get("style")) for button in shadow_actions_blocks["elements"]
    ]

    assert live_fields == shadow_fields
