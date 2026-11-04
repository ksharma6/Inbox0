from datetime import datetime, timedelta

from src.eval.app_mode import AppMode
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler

# def test_gmail_writer_labels():


def test_shadow_writer_labels(mocker):
    slack_app = mocker.Mock()
    shadow_writer = mocker.Mock(app_mode=AppMode.SHADOW)
    draft_id = "draft-abc-123"
    handler = DraftApprovalHandler(gmail_writer=shadow_writer, slack_app=slack_app)
    handler.draft_timeouts[draft_id] = datetime.now() + timedelta(hours=24)

    message = handler._create_approval_message(
        decoded_draft={
            "sender": "test sender",
            "recipient": "test recipient",
            "subject": "test subject",
            "body": "test body",
        },
        draft_id=draft_id,
        workflow_run_id="workflow-run-123",
    )

    actions_block = message["blocks"][1]
    actions = [action["text"]["text"] for action in actions_block["elements"]]

    assert actions == ["👍 Would Send", "👎 Would Reject", "✏️ Would Edit"]


# build handler with a writer whose app_mode is SHADOW
# seed handler.draft_timeouts[DRAFT_ID]
# message = handler._create_approval_message(mock_email, DRAFT_ID, WORKFLOW_RUN_ID)
# find the block whose type is "actions"
# collect each button's text.text
# assert they equal the three shadow labels
