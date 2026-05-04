import os

from slack_bolt import App as SlackApp
from src.agent.agent import Agent
from src.gmail import GmailReader, GmailWriter
from src.models.agent_schemas import AgentSchema
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler
from src.workflows.workflow import EmailProcessingWorkflow


def get_workflow(slack_app: SlackApp | None = None) -> EmailProcessingWorkflow:
    """Create an email processing workflow wired to Gmail, Slack, and the LLM agent.

    The factory centralizes application dependency wiring so Flask routes, Slack
    handlers, tests, and scripts all create the workflow the same way.

    Args:
        slack_app: Optional preconfigured Slack Bolt app. Pass the app created by
            `main.py` in production so route registration and approval messages
            share the same Slack client. If omitted, this factory creates one.

    Environment variables:
        TOKENS_PATH: Path to Gmail OAuth tokens used by `GmailReader` and
            `GmailWriter`.
        SLACK_BOT_TOKEN: Slack bot token. Required only when `slack_app` is not
            provided.
        SLACK_SIGNING_SECRET: Slack signing secret. Required only when
            `slack_app` is not provided.
        OPENROUTER_API_KEY or OPENAI_API_KEY: API key used by `AgentSchema`.
        OPENROUTER_BASE_URL: Optional OpenRouter-compatible API base URL.
        OPENROUTER_MODEL or LLM_MODEL: Optional model override.
        SITE_URL: Optional site URL reported to OpenRouter.
        APP_NAME: Optional app name reported to OpenRouter.

    Returns:
        EmailProcessingWorkflow: A configured workflow instance with Gmail,
        Slack approval handling, and an agent initialized from `AgentSchema`.

    Example usage:
        ```python
        workflow = get_workflow()
        workflow.run()
        ```

        ```python
        slack_app = SlackApp(token=os.getenv("SLACK_BOT_TOKEN"))
        workflow = get_workflow(slack_app)
        ```
    """
    gmail_token = os.getenv("TOKENS_PATH")
    gmail_writer = GmailWriter(gmail_token)
    gmail_reader = GmailReader(gmail_token)

    if slack_app is None:
        slack_app = SlackApp(
            token=os.getenv("SLACK_BOT_TOKEN"),
            signing_secret=os.getenv("SLACK_SIGNING_SECRET"),
        )

    draft_handler = DraftApprovalHandler(slack_app=slack_app, gmail_writer=gmail_writer)
    agent_schema = AgentSchema()
    agent = Agent(schema=agent_schema)

    return EmailProcessingWorkflow(
        gmail_reader=gmail_reader,
        gmail_writer=gmail_writer,
        draft_handler=draft_handler,
        agent=agent,
    )
