import pytest
from src.eval.shadow_mode.shadow_gmail_writer import ShadowGmailWriter

THREAD_ID = "thread_active_123"


@pytest.fixture
def shadow_writer(mocker):
    mocker.patch("src.gmail.gmail_writer.auth_user", return_value=mocker.Mock())
    mocker.patch("src.gmail.gmail_writer.build", return_value=mocker.Mock())
    return ShadowGmailWriter(token_path="/fake/tokens/")


def test_send_draft(shadow_writer):
    draft = shadow_writer.create_draft(
        sender="me@example.com",
        recipient="them@example.com",
        subject="Shadow Mode Test",
        message="Still replying in the active Gmail thread.",
        thread_id=THREAD_ID,
    )

    shadow_message = shadow_writer.send_draft(draft)

    assert shadow_message["shadowed"] is True
    assert shadow_message["id"].startswith("shadow_msg_")
    shadow_writer.service.users.assert_not_called()


def test_send_reply(shadow_writer):
    draft = shadow_writer.create_draft(
        sender="me@example.com",
        recipient="them@example.com",
        subject="Shadow Mode Test",
        message="Still replying in the active Gmail thread.",
        thread_id=THREAD_ID,
    )

    reply = "This is a shadow response message."

    shadow_message = shadow_writer.send_reply(draft, reply)

    assert shadow_message["shadowed"] is True
    assert shadow_message["id"].startswith("shadow_msg_")
    shadow_writer.service.users.assert_not_called()
