import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional

from slack_bolt import App
from slack_bolt.context.ack import Ack
from slack_bolt.context.say import Say
from slack_sdk.errors import SlackApiError
from src.eval.app_mode import AppMode, get_app_mode
from src.eval.human_decision import HumanDecision
from src.gmail.gmail_writer import GmailWriter
from src.routes.web.schemas import ResumeAction


def get_draft_handler(slack_app):
    """Get or create the draft approval handler"""
    gmail_writer = GmailWriter(os.getenv("TOKENS_PATH"))
    draft_handler = DraftApprovalHandler(gmail_writer=gmail_writer, slack_app=slack_app, app_mode=get_app_mode())
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

    def __init__(self, gmail_writer: GmailWriter, slack_app: App, app_mode: AppMode = AppMode.LIVE):
        """
        Initialize the draft approval handler.

        parameters:
            gmail_writer (GmailWriter): Initialized GmailWriter instance
            slack_app (App): Initialized Slack App instance
            app_mode (AppMode): Execution mode. In SHADOW, the intercepted
                actions use "Would ..." button labels. Defaults to LIVE so the
                handler behaves exactly as before unless shadow mode is opted in.
        """
        self.gmail_writer = gmail_writer
        self.slack_app = slack_app
        self.app_mode = app_mode
        self.pending_drafts = {}
        self.draft_timeouts = {}
        self.DRAFT_TIMEOUT_HOURS = 24

    def send_draft_for_approval(
        self,
        draft: Dict,
        slack_user_id: str,
        workflow_run_id: Optional[str] = None,
        email_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Optional[str]:
        """Post a draft to Slack with approval buttons and track it as pending.

        Args:
            draft (Dict): Gmail draft dictionary produced by create_draft().
            slack_user_id (str): Slack user ID the approval request is sent to.
            workflow_run_id (Optional[str]): Workflow run ID to resume when the
                user acts on the draft. Defaults to None.
            email_id (Optional[str]): Identifier of the source email, stored with
                the pending draft so later actions can reference it. Defaults to
                None.
            thread_id (Optional[str]): Identifier of the source thread, stored
                with the pending draft. Defaults to None.

        Returns:
            Optional[str]: The generated draft ID used to track the draft, or
                None if the approval message could not be sent.
        """
        try:
            draft_id = str(uuid.uuid4())

            decoded_draft = self.gmail_writer.send_draft_slack(draft)

            # create message for approval
            self.pending_drafts[draft_id] = {
                "draft": draft,
                "decoded_draft": decoded_draft,
                "slack_user_id": slack_user_id,
                "workflow_run_id": workflow_run_id,
                "email_id": email_id,
                "thread_id": thread_id,
                "created_at": datetime.now(),
                "status": "pending",
            }

            self.draft_timeouts[draft_id] = datetime.now() + timedelta(hours=self.DRAFT_TIMEOUT_HOURS)

            approval_message = self._create_approval_message(decoded_draft, draft_id, workflow_run_id)

            # Send to Slack
            target = slack_user_id
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

    def _create_approval_message(
        self, decoded_draft: Dict, draft_id: str, workflow_run_id: Optional[str] = None
    ) -> Dict:
        """
        Create the approval message with interactive buttons.

        parameters:
            decoded_draft (Dict): Decoded draft data
            draft_id (str): Unique draft identifier
            workflow_run_id (Optional[str]): Workflow run ID to include in Slack action values

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

        def action_value(action_type: str) -> str:
            if workflow_run_id:
                return f"{action_type}:{workflow_run_id}:{draft_id}"
            return f"{action_type}_{draft_id}"

        is_shadow = self.app_mode.is_shadow
        approve_label = "👻 Would Send" if is_shadow else "✅ Approve & Send"
        reject_label = "👻 Would Reject" if is_shadow else "❌ Reject"

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
                            "text": approve_label,
                            "emoji": True,
                        },
                        "style": "primary",
                        "value": action_value("approve"),
                        "action_id": "approve_draft",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": reject_label,
                            "emoji": True,
                        },
                        "style": "danger",
                        "value": action_value("reject"),
                        "action_id": "reject_draft",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "💾 Save Draft",
                            "emoji": True,
                        },
                        "value": action_value("save"),
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

    def handle_approval_action(self, ack: Ack, body: Dict, say: Say) -> Optional[HumanDecision]:
        """Handle an approve, reject, or save button click on a draft.

        Args:
            ack (Ack): Slack acknowledgment function, called immediately.
            body (Dict): Slack request body containing the action and user.
            say (Say): Slack say function used to reply to the user.

        Returns:
            Optional[HumanDecision]: The decision produced by the action, or None
                when no action was recorded (the draft is missing or expired, the
                action is unknown, or an error occurred).
        """
        try:
            ack()

            # extract action details
            action = body["actions"][0]
            value = action["value"]
            user_id = body["user"]["id"]

            if ":" in value:
                action_type, _, draft_id = value.split(":", 2)
            else:
                action_type, draft_id = value.split("_", 1)

            # Check if draft exists and is still pending
            if draft_id not in self.pending_drafts:
                say(text="❌ This draft has expired or doesn't exist.")
                return None

            # Check if draft has expired
            if datetime.now() > self.draft_timeouts[draft_id]:
                say(text="❌ This draft has expired.")
                self._cleanup_draft(draft_id)
                return None

            # Handle different actions
            if action_type == "approve":
                return self._handle_approve(draft_id, user_id, say)
            elif action_type == "reject":
                return self._handle_reject(draft_id, user_id, say)
            elif action_type == "save":
                return self._handle_save(draft_id, user_id, say)
            else:
                say(text="❌ Unknown action.")
                return None

        except Exception as e:
            logging.exception("Error handling approval action: %s", e)
            say(text="❌ An error occurred while processing your request.")
            return None

    def _build_decision(
        self,
        action: ResumeAction,
        draft_id: str,
        user_id: str,
        success: bool,
        gmail_message_id: Optional[str] = None,
        gmail_draft_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> HumanDecision:
        """Assemble a HumanDecision for an action taken on a pending draft.

        Reads the workflow run, email, and thread identifiers stored with the
        pending draft (when present) and combines them with the outcome fields.

        Args:
            action (ResumeAction): The action the user took on the draft.
            draft_id (str): Identifier of the draft acted on.
            user_id (str): Slack user ID of the acting user.
            success (bool): Whether the action completed successfully.
            gmail_message_id (Optional[str]): Sent message ID, when a send
                occurred. Defaults to None.
            gmail_draft_id (Optional[str]): Saved draft ID, when a save occurred.
                Defaults to None.
            error (Optional[str]): Error message when the action failed. Defaults
                to None.

        Returns:
            HumanDecision: The assembled decision record.
        """
        draft_data = self.pending_drafts.get(draft_id, {})
        return HumanDecision.from_resume_action(
            action,
            workflow_run_id=draft_data.get("workflow_run_id"),
            draft_id=draft_id,
            slack_user_id=user_id,
            email_id=draft_data.get("email_id"),
            thread_id=draft_data.get("thread_id"),
            success=success,
            gmail_message_id=gmail_message_id,
            gmail_draft_id=gmail_draft_id,
            error=error,
        )

    def _handle_approve(self, draft_id: str, user_id: str, say: Say) -> HumanDecision:
        """Send the approved draft and return the resulting decision.

        Args:
            draft_id (str): Identifier of the draft being approved.
            user_id (str): Slack user ID of the user who approved the draft.
            say (Say): Slack say function used to reply to the user.

        Returns:
            HumanDecision: Record of the approve action, carrying the sent
                message ID on success or an error message on failure.
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

                return self._build_decision(
                    ResumeAction.APPROVE_DRAFT,
                    draft_id,
                    user_id,
                    success=True,
                    gmail_message_id=result.get("id"),
                )

            say(text="❌ Failed to send email. Please try again.")
            decision = self._build_decision(
                ResumeAction.APPROVE_DRAFT,
                draft_id,
                user_id,
                success=False,
                error="send_draft returned no result",
            )
            self._cleanup_draft(draft_id)
            return decision

        except Exception as e:
            logging.exception("Error approving draft: %s", e)
            say(text="❌ An error occurred while sending the email.")
            return self._build_decision(
                ResumeAction.APPROVE_DRAFT,
                draft_id,
                user_id,
                success=False,
                error=str(e),
            )

    def _handle_reject(self, draft_id: str, user_id: str, say: Say) -> HumanDecision:
        """Mark the draft as rejected and return the resulting decision.

        Args:
            draft_id (str): Identifier of the draft being rejected.
            user_id (str): Slack user ID of the user who rejected the draft.
            say (Say): Slack say function used to reply to the user.

        Returns:
            HumanDecision: Record of the reject action, with no Gmail identifiers
                and an error message only if rejection handling failed.
        """
        logging.info("Draft rejected - draft_id=%s user_id=%s", draft_id, user_id)
        try:
            draft_data = self.pending_drafts[draft_id]

            self._update_original_message(draft_id, "❌ *REJECTED*", "danger")

            say(text="❌ Email draft rejected.")

            draft_data["status"] = "rejected"
            draft_data["rejected_by"] = user_id
            draft_data["rejected_at"] = datetime.now()

            return self._build_decision(ResumeAction.REJECT_DRAFT, draft_id, user_id, success=True)

        except Exception as e:
            logging.exception("Error rejecting draft: %s", e)
            say(text="❌ An error occurred while rejecting the draft.")
            return self._build_decision(
                ResumeAction.REJECT_DRAFT,
                draft_id,
                user_id,
                success=False,
                error=str(e),
            )

    def _handle_save(self, draft_id: str, user_id: str, say: Say) -> HumanDecision:
        """Save the draft to Gmail and return the resulting decision.

        Args:
            draft_id (str): Identifier of the draft being saved.
            user_id (str): Slack user ID of the user who saved the draft.
            say (Say): Slack say function used to reply to the user.

        Returns:
            HumanDecision: Record of the save action, carrying the saved Gmail
                draft ID on success or an error message on failure.
        """
        logging.info("Draft saved - draft_id=%s user_id=%s", draft_id, user_id)
        try:
            draft_data = self.pending_drafts[draft_id]
            draft = draft_data["draft"]
            saved_draft = self.gmail_writer.save_draft(draft)

            self._update_original_message(draft_id, "✅ *SAVED*", "success")

            say(text="✅ Email draft saved successfully.")

            gmail_draft_id = saved_draft.get("id") if saved_draft else None
            return self._build_decision(
                ResumeAction.SAVE_DRAFT,
                draft_id,
                user_id,
                success=saved_draft is not None,
                gmail_draft_id=gmail_draft_id,
            )

        except Exception as e:
            logging.exception("Error handling save request: %s", e)
            say(text="❌ An error occurred while processing save request.")
            return self._build_decision(
                ResumeAction.SAVE_DRAFT,
                draft_id,
                user_id,
                success=False,
                error=str(e),
            )

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
