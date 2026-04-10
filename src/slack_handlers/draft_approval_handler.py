import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional

from slack_bolt import App
from slack_bolt.context.ack import Ack
from slack_bolt.context.say import Say
from slack_sdk.errors import SlackApiError
from src.gmail.gmail_writer import GmailWriter


def get_draft_handler(slack_app):
    """Get or create the draft approval handler"""
    gmail_writer = GmailWriter(os.getenv("TOKENS_PATH"))
    draft_handler = DraftApprovalHandler(gmail_writer=gmail_writer, slack_app=slack_app)
    return draft_handler


class DraftApprovalHandler:
    """
    Handles email draft approvals through Slack interactive components.
    Manages draft storage, approval/rejection workflows, and user notifications.

    attributes:
        gmail_writer (GmailWriter): Initialized GmailWriter instance
        slack_app (App): Initialized Slack App instance
        pending_drafts (Dict): Store pending drafts: {draft_id: draft_data}
        draft_timeouts (Dict): Store timeout info: {draft_id: expiry_time}
        DRAFT_TIMEOUT_HOURS (int): Drafts expire after set number of hours (24 hours by default)
    """

    def __init__(self, gmail_writer: GmailWriter, slack_app: App):
        """
        Initialize the draft approval handler.

        parameters:
            gmail_writer (GmailWriter): Initialized GmailWriter instance
            slack_app (App): Initialized Slack App instance
        """
        self.gmail_writer = gmail_writer
        self.slack_app = slack_app
        self.pending_drafts = {}
        self.draft_timeouts = {}
        self.DRAFT_TIMEOUT_HOURS = 24

    def send_draft_for_approval(self, draft: Dict, user_id: str) -> Optional[str]:
        """
        Send a draft email for approval with interactive buttons.

        parameters:
            draft (Dict): Gmail draft dictionary from create_draft()
            user_id (str): Slack user ID to send approval request to

        Returns:
            str: The draft ID for tracking, or None if failed to send draft for approval
        """
        try:
            draft_id = str(uuid.uuid4())

            decoded_draft = self.gmail_writer.send_draft_slack(draft)

            # create message for approval
            self.pending_drafts[draft_id] = {
                "draft": draft,
                "decoded_draft": decoded_draft,
                "user_id": user_id,
                "created_at": datetime.now(),
                "status": "pending",
            }

            self.draft_timeouts[draft_id] = datetime.now() + timedelta(hours=self.DRAFT_TIMEOUT_HOURS)

            approval_message = self._create_approval_message(decoded_draft, draft_id)

            # Send to Slack
            target = user_id
            response = self.slack_app.client.chat_postMessage(
                channel=target,
                text=approval_message["text"],
                blocks=approval_message["blocks"],
            )

            self.pending_drafts[draft_id]["slack_message_ts"] = response["ts"]
            self.pending_drafts[draft_id]["slack_channel"] = target

            return draft_id

        except SlackApiError as e:
            logging.exception("Error sending draft for approval: %s", e.response["error"])
            raise
        except Exception:
            logging.exception("Unexpected error sending draft for approval")
            raise

    def _create_approval_message(self, decoded_draft: Dict, draft_id: str) -> Dict:
        """
        Create the approval message with interactive buttons.

        parameters:
            decoded_draft (Dict): Decoded draft data
            draft_id (str): Unique draft identifier

        Returns:
            Dict: Message text and blocks for Slack approval message
        """
        # create email draft
        text = "*Email Draft for Approval*\n\n"
        text += f"*From:* {decoded_draft.get('sender', 'N/A')}\n"
        text += f"*To:* {decoded_draft.get('recipient', 'N/A')}\n"
        text += f"*Subject:* {decoded_draft.get('subject', 'N/A')}\n"
        text += f"*Body:* {decoded_draft.get('body', 'N/A')}\n"

        attachments = decoded_draft.get("attachment", [])
        if attachments:
            attachment_list = ", ".join(attachments)
            text += f"*Attachments:* {attachment_list}\n"

        # define slack blocks for approval message
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {
                "type": "actions",
                "block_id": f"draft_approval_{draft_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "✅ Approve & Send",
                            "emoji": True,
                        },
                        "style": "primary",
                        "value": f"approve_{draft_id}",
                        "action_id": "approve_draft",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "❌ Reject",
                            "emoji": True,
                        },
                        "style": "danger",
                        "value": f"reject_{draft_id}",
                        "action_id": "reject_draft",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "💾 Save Draft",
                            "emoji": True,
                        },
                        "value": f"save_{draft_id}",
                        "action_id": "save_draft",
                    },
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*Draft ID:* {draft_id[:8]}... | "
                            f"*Expires:* {self.draft_timeouts[draft_id].strftime('%Y-%m-%d %H:%M')}"
                        ),
                    }
                ],
            },
        ]

        return {"text": text, "blocks": blocks}

    def handle_approval_action(self, ack: Ack, body: Dict, say: Say) -> None:
        """
        Handle approval/rejection button clicks.

        parameters:
            ack (Ack): Slack acknowledgment function
            body (Dict): Request body containing action details
            say (Say): Slack say function for responses
        """
        try:
            ack()

            # extract action details
            action = body["actions"][0]
            value = action["value"]
            user_id = body["user"]["id"]

            action_type, draft_id = value.split("_", 1)

            # Check if draft exists and is still pending
            if draft_id not in self.pending_drafts:
                say(text="❌ This draft has expired or doesn't exist.")
                return

            # Check if draft has expired
            if datetime.now() > self.draft_timeouts[draft_id]:
                say(text="❌ This draft has expired.")
                self._cleanup_draft(draft_id)
                return

            # Handle different actions
            if action_type == "approve":
                self._handle_approve(draft_id, user_id, say)
            elif action_type == "reject":
                self._handle_reject(draft_id, user_id, say)
            elif action_type == "save":
                self._handle_save(draft_id, user_id, say)
            else:
                say(text="❌ Unknown action.")

        except Exception as e:
            logging.exception("Error handling approval action: %s", e)
            say(text="❌ An error occurred while processing your request.")

    def _handle_approve(self, draft_id: str, user_id: str, say: Say) -> None:
        """Handle draft approval request

        parameters:
            draft_id (str): Unique draft identifier
            user_id (str): Slack user ID
            say (Say): Slack say function for responses
        """
        logging.info("Draft approved - draft_id=%s user_id=%s", draft_id, user_id)
        try:
            draft_data = self.pending_drafts[draft_id]
            draft = draft_data["draft"]

            result = self.gmail_writer.send_draft(draft)

            if result:
                self._update_original_message(draft_id, "✅ *APPROVED & SENT*", "success")
                say(text=f"✅ Email approved and sent successfully!\n*Message ID:* {result.get('id', 'N/A')}")

                draft_data["status"] = "approved"
                draft_data["approved_by"] = user_id
                draft_data["approved_at"] = datetime.now()

            else:
                say(text="❌ Failed to send email. Please try again.")
                self._cleanup_draft(draft_id)

        except Exception as e:
            logging.exception("Error approving draft: %s", e)
            say(text="❌ An error occurred while sending the email.")

    def _handle_reject(self, draft_id: str, user_id: str, say: Say) -> None:
        """Handle draft rejection request

        parameters:
            draft_id (str): Unique draft identifier
            user_id (str): Slack user ID
            say (Say): Slack say function for responses
        """
        logging.info("Draft rejected - draft_id=%s user_id=%s", draft_id, user_id)
        try:
            draft_data = self.pending_drafts[draft_id]

            self._update_original_message(draft_id, "❌ *REJECTED*", "danger")

            say(text="❌ Email draft rejected.")

            draft_data["status"] = "rejected"
            draft_data["rejected_by"] = user_id
            draft_data["rejected_at"] = datetime.now()

        except Exception as e:
            logging.exception("Error rejecting draft: %s", e)
            say(text="❌ An error occurred while rejecting the draft.")

    def _handle_save(self, draft_id: str, user_id: str, say: Say) -> None:
        """Handle draft save request

        parameters:
            draft_id (str): Unique draft identifier
            user_id (str): Slack user ID
            say (Say): Slack say function for responses
        """
        logging.info("Draft saved - draft_id=%s user_id=%s", draft_id, user_id)
        try:
            draft_data = self.pending_drafts[draft_id]
            draft = draft_data["draft"]
            self.gmail_writer.save_draft(draft)

            self._update_original_message(draft_id, "✅ *SAVED*", "success")

            say(text="✅ Email draft saved successfully.")

        except Exception as e:
            logging.exception("Error handling save request: %s", e)
            say(text="❌ An error occurred while processing save request.")

    def _update_original_message(self, draft_id: str, status_text: str, color: str) -> None:
        """Update the user with status message, removing original approval message and buttons

        parameters:
            draft_id (str): Unique draft identifier
            status_text (str): Status text
            color (str): Color
        """
        logging.info(
            "Updating original message - draft_id=%s status_text=%s color=%s",
            draft_id,
            status_text,
            color,
        )
        try:
            draft_data = self.pending_drafts[draft_id]

            if "slack_message_ts" in draft_data and "slack_channel" in draft_data:
                self.slack_app.client.chat_update(
                    channel=draft_data["slack_channel"],
                    ts=draft_data["slack_message_ts"],
                    text=f"{status_text}\n\n*Original draft has been processed.*",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"{status_text}\n\n*Original draft has been processed.*",
                            },
                        }
                    ],
                )
        except Exception as e:
            logging.exception("Error updating original message: %s", e)

    def _cleanup_draft(self, draft_id: str) -> None:
        """Remove draft from storage

        parameters:
            draft_id (str): Unique draft identifier
        """
        logging.info("Cleaning up draft - draft_id=%s", draft_id)
        if draft_id in self.pending_drafts:
            del self.pending_drafts[draft_id]
        if draft_id in self.draft_timeouts:
            del self.draft_timeouts[draft_id]
