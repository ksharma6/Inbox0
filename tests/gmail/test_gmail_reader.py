"""Tests for Gmail reader hardening and ``EmailMessage`` validation.

Covers the defensive changes in ``src/gmail/gmail_reader.py`` and
``src/models/gmail.py``:

- ``EmailMessage.thread_id`` now requires ``min_length=1`` so the silent
  default-to-empty-string from the Gmail API fails at model construction.
- ``_get_email_message`` logs ``[GMAIL_PAYLOAD_MISSING]`` when the API
  response is missing ``payload``, and ``[GMAIL_FETCH_ERROR]`` when any
  exception occurs while processing a message.
- ``_get_email_body`` tolerates ``None`` payloads and ``parts: None``
  without raising ``TypeError``.
"""

import base64
import logging

import pytest
from pydantic import ValidationError
from src.gmail.gmail_reader import GmailReader
from src.models.gmail import EmailMessage

VALID_THREAD_ID = "thread_abc123"


@pytest.fixture
def reader(mocker):
    """Build a ``GmailReader`` with auth + service mocked out.

    The real ``__init__`` calls ``auth_user`` and ``googleapiclient.build``.
    Patching both lets us instantiate cleanly and then stub the service
    response per test.
    """
    mocker.patch("src.gmail.gmail_reader.auth_user", return_value=mocker.Mock())
    mocker.patch("src.gmail.gmail_reader.build", return_value=mocker.Mock())
    return GmailReader(path="/fake/path")


def _stub_service_response(reader, response):
    """Wire the mocked Gmail service chain to return ``response`` from ``execute()``."""
    reader.service.users.return_value.messages.return_value.get.return_value.execute.return_value = response


def _valid_email_message_kwargs(**overrides):
    base = {
        "id": "m1",
        "subject": "s",
        "from_email": "a@b.com",
        "to_email": "c@d.com",
        "date": "now",
        "body": "",
        "thread_id": VALID_THREAD_ID,
    }
    base.update(overrides)
    return base


class TestEmailMessageThreadIdValidation:
    """``EmailMessage.thread_id`` must be non-empty (``min_length=1``)."""

    def test_accepts_non_empty_thread_id(self):
        msg = EmailMessage(**_valid_email_message_kwargs())
        assert msg.thread_id == VALID_THREAD_ID

    def test_rejects_empty_thread_id(self):
        with pytest.raises(ValidationError) as exc_info:
            EmailMessage(**_valid_email_message_kwargs(thread_id=""))
        errors = exc_info.value.errors()
        assert any(err["loc"] == ("thread_id",) for err in errors)

    def test_rejects_missing_thread_id(self):
        kwargs = _valid_email_message_kwargs()
        kwargs.pop("thread_id")
        with pytest.raises(ValidationError) as exc_info:
            EmailMessage(**kwargs)
        assert any(err["loc"] == ("thread_id",) for err in exc_info.value.errors())


class TestGetEmailMessagePayloadGuard:
    """``_get_email_message`` logs and returns ``None`` when payload is absent."""

    def test_missing_payload_returns_none_and_logs(self, reader, caplog):
        msg_id = "msg_missing_payload"
        _stub_service_response(reader, {"id": msg_id})

        with caplog.at_level(logging.WARNING):
            result = reader._get_email_message(msg_id)

        assert result is None
        assert any(
            "[GMAIL_PAYLOAD_MISSING]" in record.getMessage() and msg_id in record.getMessage()
            for record in caplog.records
        )

    def test_none_payload_returns_none_and_logs(self, reader, caplog):
        msg_id = "msg_none_payload"
        _stub_service_response(reader, {"id": msg_id, "payload": None})

        with caplog.at_level(logging.WARNING):
            result = reader._get_email_message(msg_id)

        assert result is None
        assert any("[GMAIL_PAYLOAD_MISSING]" in r.getMessage() for r in caplog.records)


class TestGetEmailMessageExceptionLogging:
    """Exceptions during processing emit ``[GMAIL_FETCH_ERROR]`` logs."""

    def test_empty_thread_id_in_api_response_logs_fetch_error(self, reader, caplog):
        """Gmail returning ``threadId=''`` now trips the model validator.

        The resulting ``ValidationError`` is caught by the broad ``except``
        in ``_get_email_message`` and surfaced as ``[GMAIL_FETCH_ERROR]``.
        """
        msg_id = "msg_empty_thread"
        _stub_service_response(
            reader,
            {
                "id": msg_id,
                "threadId": "",
                "payload": {"headers": []},
                "labelIds": [],
            },
        )

        with caplog.at_level(logging.ERROR):
            result = reader._get_email_message(msg_id, include_body=False)

        assert result is None
        assert any(
            "[GMAIL_FETCH_ERROR]" in record.getMessage() and msg_id in record.getMessage() for record in caplog.records
        )

    def test_valid_response_returns_email_message_without_error_logs(self, reader, caplog):
        msg_id = "msg_ok"
        _stub_service_response(
            reader,
            {
                "id": msg_id,
                "threadId": VALID_THREAD_ID,
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Hi"},
                        {"name": "From", "value": "x@y.com"},
                        {"name": "To", "value": "me@y.com"},
                        {"name": "Date", "value": "Thu, 01 Jan 2026"},
                    ],
                },
                "labelIds": ["INBOX"],
            },
        )

        with caplog.at_level(logging.WARNING):
            result = reader._get_email_message(msg_id, include_body=False)

        assert isinstance(result, EmailMessage)
        assert result.thread_id == VALID_THREAD_ID
        assert result.subject == "Hi"
        assert not any(
            "[GMAIL_PAYLOAD_MISSING]" in r.getMessage() or "[GMAIL_FETCH_ERROR]" in r.getMessage()
            for r in caplog.records
        )


class TestGetEmailBodyHardening:
    """``_get_email_body`` tolerates ``None`` / missing ``parts`` without raising."""

    def test_none_payload_returns_empty_string(self, reader):
        assert reader._get_email_body(None) == ""

    def test_parts_is_none_returns_empty_string(self, reader):
        """Defends against the rare ``{'parts': None}`` shape Gmail can return."""
        assert reader._get_email_body({"parts": None}) == ""

    def test_payload_without_parts_or_body_returns_empty(self, reader):
        assert reader._get_email_body({"mimeType": "text/plain"}) == ""

    def test_plain_text_body_is_decoded(self, reader):
        encoded = base64.urlsafe_b64encode(b"hello world").decode("utf-8")
        payload = {"mimeType": "text/plain", "body": {"data": encoded}}
        assert reader._get_email_body(payload) == "hello world"

    def test_nested_parts_recurse(self, reader):
        encoded = base64.urlsafe_b64encode(b"nested body").decode("utf-8")
        payload = {
            "parts": [
                {"parts": [{"mimeType": "text/plain", "body": {"data": encoded}}]},
            ],
        }
        assert reader._get_email_body(payload) == "nested body"
