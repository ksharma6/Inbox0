import logging
import uuid
from typing import Optional

from src.eval.event_log import EventLog
from src.eval.event_schema import EmailSendShadowed
from src.gmail.gmail_writer import GmailWriter

logger = logging.getLogger(__name__)


def _shadow_message_id() -> str:
    return f"shadow_msg_{uuid.uuid4()}"


class ShadowGmailWriter(GmailWriter):
    """Suppress outbound sends while preserving other Gmail operations.

    Send methods return synthetic message IDs instead of contacting Gmail, and
    record an ``EmailSendShadowed`` event for each suppressed send when an event
    log is configured. Explicit draft saves retain the parent behavior and
    create real Gmail drafts.
    """

    def __init__(self, token_path, event_log: Optional[EventLog] = None):
        """Initialize the writer and optionally attach an event log.

        Args:
            token_path (str): Path to the OAuth token file used to authenticate
                with Gmail, forwarded to the parent writer.
            event_log (Optional[EventLog]): Sink that receives an
                ``EmailSendShadowed`` event for each suppressed send. When None,
                sends are suppressed silently. Defaults to None.
        """
        super().__init__(token_path)
        self.event_log = event_log

    def send_draft(self, draft, workflow_run_id=None, draft_id=None):
        """Suppress an outbound send and return a synthetic message id.

        Args:
            draft (dict): The draft email message dictionary that would have been
                sent. Not transmitted in shadow mode.
            workflow_run_id (Optional[str]): Identifier of the originating
                workflow run. Required to record an event. Defaults to None.
            draft_id (Optional[str]): Identifier of the originating draft, stored
                on the recorded event. Defaults to None.

        Returns:
            dict: A payload of the form ``{"id": <synthetic id>}`` mirroring the
                shape of a real send response.
        """
        shadow_id = _shadow_message_id()
        logger.info("Shadow mode: suppressed send_draft, shadow_id=%s", shadow_id)
        self._record_shadowed("send_draft", shadow_id, workflow_run_id, draft_id)
        return {"id": shadow_id}

    def send_reply(self, original_message, reply_message, workflow_run_id=None, draft_id=None):
        """Suppress an outbound reply and return a synthetic message id.

        Args:
            original_message (dict): The message being replied to. Not
                transmitted in shadow mode.
            reply_message (str): The reply body that would have been sent. Not
                transmitted in shadow mode.
            workflow_run_id (Optional[str]): Identifier of the originating
                workflow run. Required to record an event. Defaults to None.
            draft_id (Optional[str]): Identifier of the originating draft, stored
                on the recorded event. Defaults to None.

        Returns:
            dict: A payload of the form ``{"id": <synthetic id>}`` mirroring the
                shape of a real send response.
        """
        shadow_id = _shadow_message_id()
        logger.info("Shadow mode: suppressed send_reply, shadow_id=%s", shadow_id)
        self._record_shadowed("send_reply", shadow_id, workflow_run_id, draft_id)
        return {"id": shadow_id}

    def _record_shadowed(self, send_path, shadow_id, workflow_run_id, draft_id):
        """Record an EmailSendShadowed event when enough context is available.

        Args:
            send_path (str): Which send operation was intercepted, one of
                "send_draft" or "send_reply".
            shadow_id (str): The synthetic message id returned in place of a real
                sent-message id.
            workflow_run_id (Optional[str]): Identifier of the originating
                workflow run. Emission is skipped when None.
            draft_id (Optional[str]): Identifier of the originating draft.
        """
        if self.event_log is None or workflow_run_id is None:
            return
        self.event_log.record(
            EmailSendShadowed(
                workflow_run_id=workflow_run_id,
                shadow_message_id=shadow_id,
                send_path=send_path,
                draft_id=draft_id,
            )
        )
