import logging
import uuid

from src.gmail.gmail_writer import GmailWriter

logger = logging.getLogger(__name__)


class ShadowGmailWriter(GmailWriter):
    """Intercept outbound email sends while preserving Gmail draft operations in shadow mode.
    The inherited Gmail client remains available for creating, decoding, and
    saving drafts. Send operations return synthetic results without calling
    Gmail's message-send API.
    Args:
        token_path (str): Directory containing the user's Gmail OAuth tokens.
    """

    def send_draft(self, draft):
        """Intercept a draft send and return a synthetic message result in shadow mode.
        Logs the intercepted operation without sending the draft through Gmail.
        Args:
            draft (dict): Encoded email draft that would have been sent.
        Returns:
            dict: Synthetic result containing a shadow message ID and marker.
        """
        shadow_message_id = f"shadow_msg_{str(uuid.uuid4())}"

        shadow_message = {
            "id": shadow_message_id,
            "shadowed": True,
        }

        logger.info(f"Intercepted Gmail draft send in shadow mode: message_id {shadow_message_id}")
        return shadow_message

    def send_reply(self, original_message, reply_message):
        """Intercept a reply send and return a synthetic message result in shadow mode.
        Logs the intercepted operation without sending the reply through Gmail.
        Args:
            original_message (dict): Original Gmail message being replied to.
            reply_message (str): Body of the reply that would have been sent.
        Returns:
            dict: Synthetic result containing a shadow message ID and marker.
        """

        shadow_message_id = f"shadow_msg_{str(uuid.uuid4())}"

        shadow_message = {
            "id": shadow_message_id,
            "shadowed": True,
        }

        logger.info(f"Intercepted Gmail send reply in shadow mode: message_id {shadow_message_id}")
        return shadow_message
