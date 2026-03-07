import os

from openrouter import OpenRouter
from slack_bolt import App
from src.gmail import GmailReader, GmailWriter
from src.slack_handlers.draft_approval_handler import get_draft_handler
from src.workflows.workflow import EmailProcessingWorkflow


def get_workflow(slack_app: App):
    """Initialize EmailProcessingWorkflow with all dependencies outlined in .env file and return to user

    Returns:
        EmailProcessingWorkflow: A configured workflow instance

    Example:
        workflow = get_workflow(slack_app)
        workflow.run()
    """
    gmail_token = os.getenv("TOKENS_PATH")
    gmail_writer = GmailWriter(gmail_token)
    gmail_reader = GmailReader(gmail_token)

    draft_handler = get_draft_handler(slack_app)

    openrouter_client = OpenRouter(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url=os.getenv("OPENROUTER_BASE_URL"),
        app_name=os.getenv("APP_NAME"),
    )
    return EmailProcessingWorkflow(
        gmail_reader=gmail_reader,
        gmail_writer=gmail_writer,
        draft_handler=draft_handler,
        openrouter_client=openrouter_client,
    )
