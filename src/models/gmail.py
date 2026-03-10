from typing import List

from pydantic import BaseModel, Field
from src.models.toolfunction import ParamProperties, ToolFunction, ToolParams


class EmailHeader(BaseModel):
    """Schema for email header information"""

    name: str = Field(..., description="Header name (e.g., 'Subject', 'From', 'To')")
    value: str = Field(..., description="Header value")


class EmailBody(BaseModel):
    """Schema for email body content"""

    content: str = Field(..., description="The email body content (cleaned of HTML)")
    mime_type: str = Field(..., description="MIME type of the body content")
    is_html: bool = Field(..., description="Whether the content is HTML")


class EmailMessage(BaseModel):
    """Schema for a complete email message"""

    id: str = Field(..., description="Gmail message ID")
    subject: str = Field(..., description="Email subject line")
    from_email: str = Field(..., description="Sender's email address")
    to_email: str = Field(..., description="Recipient's email address")
    date: str = Field(..., description="Email date as string")
    body: str = Field(..., description="Cleaned email body content")
    is_read: bool = Field(default=False, description="Whether the email has been read")
    is_important: bool = Field(
        default=False, description="Whether the email is marked as important"
    )
    thread_id: str = Field(..., description="Gmail thread ID")


class EmailSummary(BaseModel):
    """Schema for email summary information"""

    total_unread: int = Field(..., description="Total number of unread emails")
    emails: List[EmailMessage] = Field(..., description="List of email messages")
    summary_by_sender: dict = Field(..., description="Summary grouped by sender")
    urgent_emails: List[EmailMessage] = Field(
        ..., description="Emails marked as urgent or important"
    )
    recent_activity: str = Field(..., description="Summary of recent email activity")


class GmailReaderToolFunction:
    """
    Defines ToolFunction schemas for GmailReader operations
    """

    @staticmethod
    def generate_read_emails_schema() -> ToolFunction:
        """
        Returns Pydantic ToolFunction for `GmailReader.read_email()`
        """
        return ToolFunction(
            name="read_emails",
            description="Read and retrieve the most recent emails from Gmail inbox. Returns formatted email data including subject, sender, date, and body content.",
            parameters=ToolParams(
                type="object",
                properties={
                    "count": ParamProperties(
                        type="integer",
                        description="Number of emails to retrieve (default: 5, max: 50)",
                    ),
                    "unread_only": ParamProperties(
                        type="boolean",
                        description="Whether to retrieve only unread emails (default: false)",
                    ),
                    "include_body": ParamProperties(
                        type="boolean",
                        description="Whether to include full email body content (default: true)",
                    ),
                },
                required=[],
            ),
        )

    @staticmethod
    def generate_get_email_by_id_schema() -> ToolFunction:
        """
        Returns Pydantic ToolFunction for getting a specific email by ID
        """
        return ToolFunction(
            name="get_email_by_id",
            description="Retrieve a specific email by its Gmail message ID",
            parameters=ToolParams(
                type="object",
                properties={
                    "email_id": ParamProperties(
                        type="string",
                        description="Gmail message ID of the email to retrieve",
                    ),
                    "include_body": ParamProperties(
                        type="boolean",
                        description="Whether to include full email body content (default: true)",
                    ),
                },
                required=["email_id"],
            ),
        )

    @staticmethod
    def generate_search_emails_schema() -> ToolFunction:
        """
        Returns Pydantic ToolFunction for searching emails
        """
        return ToolFunction(
            name="search_emails",
            description="Search emails using Gmail search query syntax",
            parameters=ToolParams(
                type="object",
                properties={
                    "query": ParamProperties(
                        type="string",
                        description="Gmail search query (e.g., 'from:example@gmail.com', 'subject:meeting', 'is:unread')",
                    ),
                    "max_results": ParamProperties(
                        type="integer",
                        description="Maximum number of results to return (default: 10, max: 50)",
                    ),
                    "include_body": ParamProperties(
                        type="boolean",
                        description="Whether to include full email body content (default: false)",
                    ),
                },
                required=["query"],
            ),
        )


class GmailToolFunction:
    """
    Defines TooFunction schema for sending emails
    """

    @staticmethod
    def generate_send_email_schema() -> ToolFunction:
        """
        Returns Pydantic ToolFunction for `GmailWriter.send_email()`
        """

        return ToolFunction(
            name="send_email",
            description="Sends an email to a recipient with a subject and body.",  # Description matches
            parameters=ToolParams(
                type="object",
                properties={
                    "sender": ParamProperties(
                        type="string", description="The sender's email address."
                    ),
                    "recipient": ParamProperties(
                        type="string", description="The recipient's email address."
                    ),
                    "subject": ParamProperties(
                        type="string", description="The subject of the email."
                    ),
                    "message": ParamProperties(
                        type="string", description="The main content of the email."
                    ),
                    "attachment_path": ParamProperties(
                        type="string", description="Path to attachment - Optional"
                    ),
                },
                required=[
                    "sender",
                    "recipient",
                    "subject",
                    "message",
                ],
            ),
        )

    @staticmethod
    def generate_create_draft_schema() -> ToolFunction:
        """
        Returns Pydantic ToolFunction for `GmailWriter.create_draft()`
        """
        return ToolFunction(
            name="create_draft",
            description="Creates an email draft with sender, recipient, subject, message, and optional attachment. Use this FIRST before sending to Slack.",
            parameters=ToolParams(
                type="object",
                properties={
                    "sender": ParamProperties(
                        type="string", description="The sender's email address."
                    ),
                    "recipient": ParamProperties(
                        type="string", description="The recipient's email address."
                    ),
                    "subject": ParamProperties(
                        type="string", description="The subject of the email."
                    ),
                    "message": ParamProperties(
                        type="string", description="The main content of the email."
                    ),
                    "attachment_path": ParamProperties(
                        type="string", description="Path to attachment - Optional"
                    ),
                },
                required=["sender", "recipient", "subject", "message"],
            ),
        )
