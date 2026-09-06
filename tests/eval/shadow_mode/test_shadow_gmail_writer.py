import pytest
from src.eval.shadow_mode.shadow_gmail_writer import ShadowGmailWriter

THREAD_ID = "thread_active_123"


@pytest.fixture
def shadow_writer(mocker):
    mocker.patch("src.gmail.gmail_writer.auth_user", return_value=mocker.Mock())
    mocker.patch("src.gmail.gmail_writer.build", return_value=mocker.Mock())
    return ShadowGmailWriter(token_path="/fake/tokens/")


def test_send_draft_returns_synthetic_result(shadow_writer):
    """Verify that shadow draft sends return a synthetic result."""
    draft = shadow_writer.create_draft(
        sender="me@example.com",
        recipient="them@example.com",
        subject="Shadow Mode Test",
        message="Still replying in the active Gmail thread.",
        thread_id=THREAD_ID,
    )

    shadow_message = shadow_writer.send_draft(draft)
    shadow_writer.service.users.assert_not_called()

    assert shadow_message["shadowed"] is True
    assert shadow_message["id"].startswith("shadow_msg_")


def test_send_draft_does_not_call_gmail(shadow_writer):
    """Verify that shadow draft sends do not call the Gmail API."""
    draft = {
        "raw": "encoded-message",
        "threadId": THREAD_ID,
    }

    shadow_writer.send_draft(draft)
    shadow_writer.service.users.assert_not_called()


def test_send_reply_returns_synthetic_result(shadow_writer):
    """Verify that shadow replies return a synthetic result."""
    original_message = {
        "threadId": THREAD_ID,
        "payload": {
            "headers": [
                {"name": "From", "value": "them@example.com"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Shadow Mode Test"},
                {"name": "Message-ID", "value": "<message-123@example.com>"},
            ]
        },
    }

    reply_message = "This is a shadow response message."

    shadow_message = shadow_writer.send_reply(original_message, reply_message)

    assert shadow_message["shadowed"] is True
    assert shadow_message["id"].startswith("shadow_msg_")


def test_send_reply_does_not_call_gmail(shadow_writer):
    """Verify that shadow replies do not call the Gmail API."""
    original_message = {
        "threadId": THREAD_ID,
        "payload": {
            "headers": [
                {"name": "From", "value": "them@example.com"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Shadow Mode Test"},
                {"name": "Message-ID", "value": "<message-123@example.com>"},
            ]
        },
    }

    reply_message = "This is a shadow response message."

    shadow_writer.send_reply(original_message, reply_message)
    shadow_writer.service.users.assert_not_called()


def test_save_draft_calls_gmail_drafts_api(shadow_writer):
    """Verify that shadow mode preserves real Gmail draft creation."""
    draft = {"raw": "encoded-message", "threadId": THREAD_ID}
    expected_body = {
        "message": {
            "raw": "encoded-message",
            "threadId": THREAD_ID,
        }
    }

    create_shadow_draft_mock = shadow_writer.service.users.return_value.drafts.return_value.create
    create_shadow_draft_mock.return_value.execute.return_value = {"id": "draft-1"}

    shadow_writer.save_draft(draft)

    create_shadow_draft_mock.assert_called_once_with(
        userId="me",
        body=expected_body,
    )
