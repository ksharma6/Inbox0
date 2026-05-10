import base64
from email import message_from_bytes
from email.policy import default

import pytest
from src.gmail.gmail_writer import GmailWriter

THREAD_ID = "thread_active_123"


@pytest.fixture
def writer(mocker):
    """Build a GmailWriter with auth and Gmail API client mocked out."""
    mocker.patch("src.gmail.gmail_writer.auth_user", return_value=mocker.Mock())
    mocker.patch("src.gmail.gmail_writer.build", return_value=mocker.Mock())
    return GmailWriter(token_path="/fake/tokens/")


def _decode_raw_message(raw_message):
    return message_from_bytes(base64.urlsafe_b64decode(raw_message), policy=default)


def test_create_draft_includes_thread_id_even_when_subject_changes(writer):
    """create_draft should keep changed subjects while adding Gmail thread metadata."""
    draft = writer.create_draft(
        sender="me@example.com",
        recipient="them@example.com",
        subject="Re: lol",
        message="Still replying in the active Gmail thread.",
        thread_id=THREAD_ID,
    )

    decoded = _decode_raw_message(draft["raw"])

    assert draft["threadId"] == THREAD_ID
    assert decoded["Subject"] == "Re: lol"
    assert decoded["To"] == "them@example.com"
    assert decoded.get_body(preferencelist=("plain",)).get_content() == "Still replying in the active Gmail thread.\n"


def test_save_draft_passes_thread_id_to_gmail(writer):
    """save_draft should pass threadId through to Gmail drafts.create."""
    draft = {"raw": "encoded-message", "threadId": THREAD_ID}
    writer.service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {"id": "draft-1"}

    writer.save_draft(draft)

    create_kwargs = writer.service.users.return_value.drafts.return_value.create.call_args.kwargs
    assert create_kwargs["body"] == {"message": {"raw": "encoded-message", "threadId": THREAD_ID}}


def test_standalone_drafts_do_not_include_thread_id(writer):
    """Drafts created without thread_id should remain standalone Gmail drafts."""
    draft = writer.create_draft(
        sender="me@example.com",
        recipient="them@example.com",
        subject="New topic",
        message="This is not a threaded reply.",
    )
    writer.service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {"id": "draft-1"}

    writer.save_draft(draft)

    assert "threadId" not in draft
    create_kwargs = writer.service.users.return_value.drafts.return_value.create.call_args.kwargs
    assert create_kwargs["body"] == {"message": {"raw": draft["raw"]}}


def test_send_draft_preserves_thread_id_in_gmail_send_body(writer):
    """send_draft must not drop threadId before calling Gmail messages.send."""
    draft = {"raw": "encoded-message", "threadId": THREAD_ID}
    writer.service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "sent-1"}

    writer.send_draft(draft)

    send_kwargs = writer.service.users.return_value.messages.return_value.send.call_args.kwargs
    assert send_kwargs["body"] == draft


def test_send_reply_uses_thread_id_when_recipient_changed_subject(writer):
    """send_reply should use threadId even when the prior message subject changed."""
    original_message = {
        "threadId": THREAD_ID,
        "payload": {
            "headers": [
                {"name": "From", "value": "them@example.com"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "lol"},
                {"name": "Message-ID", "value": "<message-123@example.com>"},
            ]
        },
    }
    writer.service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "reply-1"}

    writer.send_reply(original_message, "Yep, still part of this thread.")

    send_kwargs = writer.service.users.return_value.messages.return_value.send.call_args.kwargs
    assert send_kwargs["body"]["threadId"] == THREAD_ID

    decoded = _decode_raw_message(send_kwargs["body"]["raw"])
    assert decoded["Subject"] == "Re: lol"
    assert decoded["To"] == "them@example.com"
    assert decoded["In-Reply-To"] == "<message-123@example.com>"
    assert decoded["References"] == "<message-123@example.com>"
    assert decoded.get_body(preferencelist=("plain",)).get_content() == "Yep, still part of this thread.\n"
