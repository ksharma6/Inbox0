import logging
import uuid

from src.gmail.gmail_writer import GmailWriter

logger = logging.getLogger(__name__)


def _shadow_message_id() -> str:
    return f"shadow_msg_{uuid.uuid4()}"


class ShadowGmailWriter(GmailWriter):
    """Suppress outbound sends while preserving other Gmail operations.

    Send methods return synthetic message IDs. Explicit draft saves retain the
    parent behavior and create real Gmail drafts.
    """

    def send_draft(self, draft):
        """No-op stand-in for the outbound send. Returns a synthetic id."""
        shadow_id = _shadow_message_id()
        logger.info("Shadow mode: suppressed send_draft, shadow_id=%s", shadow_id)
        return {"id": shadow_id}

    def send_reply(self, original_message, reply_message):
        """No-op stand-in for the outbound reply. Returns a synthetic id."""
        shadow_id = _shadow_message_id()
        logger.info("Shadow mode: suppressed send_reply, shadow_id=%s", shadow_id)
        return {"id": shadow_id}
