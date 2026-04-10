import base64
import mimetypes
import os
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .gmail_authenticator import auth_user


class GmailWriter:
    def __init__(self, token_path):
        """
        Writer for Gmail that sends messages via the Gmail API.

        This client wraps the Gmail API to create drafts, send messages, and reply to emails given a thread id.

        Args:
            token_path (str): Directory containing the user's Gmail OAuth tokens (e.g.,
                `token.json`). Used by `auth_user` to obtain credentials.

        Attributes:
            path (str): Directory used to locate authentication tokens.
            creds: Gmail API credentials object.
            service: Gmail API service client object used to interact with the Gmail API.

        Example:
            writer = GmailWriter(token_path="/path/to/tokens")
            draft = writer.create_draft(
                sender="user@example.com",
                recipient="recipient@example.com",
                subject="Test Email",
                message="This is a test email",
                attachment_path="/path/to/attachment.pdf"
            )
            writer.send_draft(draft)
        """
        self.token_path = token_path
        self.creds = auth_user(self.token_path)
        self.service = build("gmail", "v1", credentials=self.creds)

    def create_draft(
        self,
        sender: str,
        recipient: str,
        subject: str,
        message: str,
        attachment_path: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Create a draft email message dictionary given the sender, recipient, subject, message,
        and optional attachment path. Dictionary is in the format of {"raw": "base64_encoded_message"}.

        Args:
            sender (str): The email address of the sender.
            recipient (str): The email address of the recipient.
            subject (str): The subject line of the email.
            message (str): The body of the email.
            attachment_path (Optional[str], optional): The path to the attachment. Defaults to None.

        Returns:
            Optional[dict]: The encoded draft email message.
        """
        try:
            # create unencoded draft object
            draft = EmailMessage()

            draft.set_content(message)

            draft["To"] = recipient
            draft["From"] = sender
            draft["Subject"] = subject

            # if attachment_path is provided, add it to the unencoded draft
            if attachment_path:
                type_subtype, _ = mimetypes.guess_type(attachment_path)
                if type_subtype is None:
                    main_type, sub_type = "application", "octet-stream"
                else:
                    main_type, sub_type = type_subtype.split("/")

                filename = os.path.basename(attachment_path)

                with open(attachment_path, "rb") as fp:
                    draft.add_attachment(
                        fp.read(),
                        maintype=main_type,
                        subtype=sub_type,
                        filename=filename,
                    )

            # encode draft
            raw_bytes = base64.urlsafe_b64encode(draft.as_bytes())
            raw_str = raw_bytes.decode()

            return {"raw": raw_str}

        except HttpError as error:
            print(f"An error occurred: {error}")
            return None

    def send_draft_slack(self, draft):
        """
        Send email draft as a message to Slack.

        Args:
            draft (dict): The draft email message.

        Returns:
            dict: The sent message details.
        """
        return self._email_message_decoder(draft)

    def send_draft(self, draft):
        """
        Send a draft email message to recipient. Sent message details are reflected in users Gmail sent folder.

        Args:
            draft (dict): The draft email message dictionary in the format of {"raw": "base64_encoded_message"}.

        Returns:
            dict: The sent message details.
        """
        send_message = self.service.users().messages().send(userId="me", body=draft).execute()
        print("Message issued successfully")

        return send_message

    def send_reply(self, original_message, reply_message):
        """
        Send a reply to an original email message given the thread id.

        Args:
            original_message (dict): The original email message dictionary in the format of
                {"payload": {"headers": [{"name": "From", "value": "sender@example.com"},
                {"name": "Subject", "value": "Test Email"}, {"name": "Message-ID", "value": "1234567890"},
                {"name": "To", "value": "recipient@example.com"}]}}.
            reply_message (str): The reply message body.

        Returns:
            dict: The sent message details.
        """
        # get headers
        headers = original_message["payload"]["headers"]
        to_address = next(header["value"] for header in headers if header["name"] == "From")
        subject = next(header["value"] for header in headers if header["name"] == "Subject")
        message_id = next(header["value"] for header in headers if header["name"] == "Message-ID")
        my_email_address = next(header["value"] for header in headers if header["name"] == "To")

        # reply subject logic
        if not subject.startswith("Re:"):
            reply_subject = f"Re: {subject}"
        else:
            reply_subject = subject

        # create reply email message
        message = EmailMessage()
        message["to"] = to_address
        message["from"] = my_email_address
        message["subject"] = reply_subject
        message["In-Reply-To"] = message_id
        message["References"] = message_id

        message.set_content(reply_message)

        # encode and send reply message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        try:
            message = self.service.users().messages().send(userId="me", body=raw_message).execute()
            print(f"Reply sent successfully! Message ID: {message['id']}")
            return message

        except HttpError as error:
            print(f"An error occurred while sending reply: {error}")
            return None

    def save_draft(self, draft):
        """
        Saves a draft email dictionary object into user's Gmail drafts folder.

        Args:
            draft (dict): The draft email message dictionary in the format of {"raw": "base64_encoded_message"}.

        Returns:
            print: Success message if draft is saved successfully.
        """
        try:
            create_draft = {"message": {"raw": draft["raw"]}}

            saved_draft = self.service.users().drafts().create(userId="me", body=create_draft).execute()
            print(f"Draft saved successfully with ID: {saved_draft.get('id', 'N/A')}")
            return saved_draft
        except HttpError as error:
            print(f"An error occurred while saving draft: {error}")
            return None

    def _email_message_decoder(self, raw_str):
        """Decodes a base64 encoded email draft dictionary and extracts its plain text body.
        Utilized by send_draft_slack.

        Args:
            raw_str: A URL-safe base64 encoded string representing the raw email draft dictionary
                in the format of {"raw": "base64_encoded_message"}.

        Returns:
            The plain text body of the email draft.
        """
        # decode the base64 string
        raw_bytes = base64.urlsafe_b64decode(raw_str["raw"])

        email_message = message_from_bytes(raw_bytes, policy=default)

        body_part = email_message.get_body(preferencelist=("plain",))
        body_content = body_part.get_content() if body_part is not None else ""

        details = {
            "sender": email_message["From"],
            "recipient": email_message["To"],
            "subject": email_message["Subject"],
            "body": body_content,
            "attachment": [],
        }

        # add attachments to details if applicable
        for part in email_message.iter_attachments():
            details["attachment"].append(part.get_filename())

        return details
