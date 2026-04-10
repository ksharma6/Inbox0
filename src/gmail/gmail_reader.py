import base64
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from src.models.gmail import EmailMessage

from .gmail_authenticator import auth_user


class GmailReader:
    """
    Reader for Gmail that authenticates and fetches messages via the Gmail API.

    This client wraps the Gmail API to retrieve messages from the user's inbox,
    search using Gmail query syntax, and fetch individual messages by ID.

    Args:
        path (str): Directory containing the user's Gmail OAuth tokens (e.g.,
            `token.json`). Used by `auth_user` to obtain credentials.

    Attributes:
        path (str): Directory used to locate authentication tokens.
        creds: OAuth credentials used for Gmail API.
        service: Gmail API service client.

    Example:
        reader = GmailReader(path="/path/to/tokens")
        emails = reader.read_emails(count=5, unread_only=True, include_body=True)
    """

    def __init__(self, path):
        self.path = path
        self.creds = auth_user(self.path)
        self.service = build("gmail", "v1", credentials=self.creds)

    def read_emails(
        self,
        count: int = 5,
        unread_only: bool = False,
        include_body: bool = True,
        primary_only: bool = True,
        thread_id: Optional[List[str]] = None,
    ) -> List[EmailMessage]:
        """
        Read emails from the user's inbox.

        Builds a Gmail query targeting the Inbox (and Primary by default), then fetches
        up to `count` messages and returns them as `EmailMessage` models.

        Args:
            count (int): Minimum number of messages to fetch (capped at 25).
            unread_only (bool): If True, restricts to unread messages.
            include_body (bool): If True, includes the parsed body text.
            primary_only (bool): If True, restricts to the Primary category.

        Returns:
            List[EmailMessage]: Messages in reverse-chronological order from the inbox.
        """

        # target inbox emails only
        query_parts = ["in:inbox"]

        if primary_only:
            query_parts.append("category:primary")

        if unread_only:
            query_parts.append("is:unread")

        query = " ".join(query_parts)

        # list of user's messages - capped at 25 messages
        list_params = {"userId": "me", "maxResults": min(count, 25), "q": query}

        results = self.service.users().messages().list(**list_params).execute()
        messages = results.get("messages", [])

        if not messages:
            print("No messages found.")
            return []

        email_messages = []
        for message in messages:
            email_msg = self._get_email_message(message["id"], include_body)
            if email_msg:
                email_messages.append(email_msg)

        return email_messages

    def get_recent_emails_in_thread(self, thread_id: str, count: int = 4) -> List[EmailMessage]:
        """
        Get the most recent emails in thread specified by thread_id.

        Args:
            thread_id (str): Unique Gmail thread identifier.
            count (int): Maximum number of messages to return.

        Returns:
            List[EmailMessage]: Messages from the given thread, if available.
        """
        return self.read_emails(count=count, thread_id=thread_id)

    def _get_email_message(
        self,
        message_id: str,
        include_body: bool = True,
        message_detail: Optional[Dict] = None,
    ) -> Optional[EmailMessage]:
        """
        Helper method to create EmailMessage object from Gmail API response.

        Args:
            message_id (str): Unique Gmail message ID.
            include_body (bool): Whether to include full email body content.
            message_detail (Optional[Dict]): Pre-fetched message detail (optional)

        Returns:
            Optional[EmailMessage]: Parsed email or None if error.
        """
        try:
            if not message_detail:
                message_detail = (
                    self.service.users().messages().get(userId="me", id=message_id, format="full").execute()
                )

            if not message_detail:
                return None

            payload = message_detail.get("payload")
            if not payload:
                return None

            headers = payload.get("headers", [])
            subject = self._get_header(headers, "Subject") or "No Subject"
            from_email = self._get_header(headers, "From") or "Unknown"
            to_email = self._get_header(headers, "To") or "Unknown"
            date_str = self._get_header(headers, "Date") or "Unknown"

            # Get email body if requested
            body = ""
            if include_body:
                raw_body = self._get_email_body(payload)
                body = self._html_parser(raw_body)

            # Get additional Gmail-specific fields
            label_ids = message_detail.get("labelIds", [])
            is_read = "UNREAD" not in label_ids
            is_important = "IMPORTANT" in label_ids
            thread_id = message_detail.get("threadId", "")

            return EmailMessage(
                id=message_id,
                subject=subject,
                from_email=from_email,
                to_email=to_email,
                date=date_str,
                body=body,
                is_read=is_read,
                is_important=is_important,
                thread_id=thread_id,
            )

        except Exception as e:
            print(f"Error processing email {message_id}: {e}")
            return None

    def _get_header(self, headers: list, name: str):
        """
        Retrieve the value of a specific email header.

        Args:
            headers (list): List of header dictionaries.
            name (str): Header name to find (e.g., 'Subject', 'From').

        Returns:
            Optional[str]: Header value if present; otherwise None.
        """

        if headers:
            for header in headers:
                if header.get("name") == name:
                    return header.get("value")

        return None

    def _html_parser(self, data: str):
        """
        Convert HTML to plain text using BeautifulSoup.

        Args:
            data (str): HTML or plain text.

        Returns:
            str: Cleaned plain-text content.
        """
        if not data or data == "":
            print("string not found")
            return ""

        soup = BeautifulSoup(data, "html.parser")

        # remove script/style tags
        for tag in soup(["script", "style"]):
            tag.decompose()

        # aggregate remaining text
        cleaned_data = soup.get_text(separator=" ", strip=True)

        return cleaned_data

    def _get_email_body(self, payload):
        """
        Extract a combined plain-text body from a Gmail message payload.

        Args:
            payload (dict): Gmail message payload.

        Returns:
            str: Concatenated text of all readable parts.
        """

        body = ""

        if "parts" in payload:
            for part in payload["parts"]:
                # recursive call for each part in payload
                body += self._get_email_body(part)
        # base case - part w/ body
        elif "body" in payload and "data" in payload["body"]:
            part_body = payload["body"]["data"]

            if payload.get("mimeType") == "text/plain":
                body += base64.urlsafe_b64decode(part_body).decode("utf-8")
            elif payload.get("mimeType") == "text/html":
                html_content = base64.urlsafe_b64decode(part_body).decode("utf-8")
                soup = BeautifulSoup(html_content, "html.parser")
                body += soup.get_text()

        return body
