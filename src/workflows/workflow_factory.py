import os

from slack_bolt import App
from src.agent.agent import Agent
from src.gmail import GmailReader, GmailWriter
from src.models.agent_schemas import (
    AgentSchema,
    get_default_api_key,
    get_default_base_url,
)
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

    agent_schema = AgentSchema(
        api_key=get_default_api_key(),
        base_url=get_default_base_url(),
        app_name=os.getenv("APP_NAME"),
    )
    agent = Agent(schema=agent_schema)

    return EmailProcessingWorkflow(
        gmail_reader=gmail_reader,
        gmail_writer=gmail_writer,
        draft_handler=draft_handler,
        agent=agent,
    )
