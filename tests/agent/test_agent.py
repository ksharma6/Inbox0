import json
import unittest
from unittest.mock import ANY, MagicMock, patch

from src.agent.agent import Agent
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
from src.models.agent_schemas import AgentSchema, ProcessRequestSchema
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler


class TestAgent(unittest.TestCase):
    """Test suite for the Agent class"""

    def setUp(self):
        """Set up the test environment by:
        1. Creating mock objects for GmailWriter, GmailReader, and DraftApprovalHandler.
        2. Creating a mock agent_schema to configure the Agent.
        3. Creating a mock OpenAI client to configure the Agent.
        4. Creating an Agent instance using the agent_schema and the mock OpenAI client.
        """
        self.mock_gmail_writer = MagicMock(spec=GmailWriter)
        self.mock_gmail_reader = MagicMock(spec=GmailReader)
        self.mock_draft_approval_handler = MagicMock(spec=DraftApprovalHandler)

        self.agent_schema = AgentSchema(
            api_key="test-key",
            model="test-model",
            available_tools={
                "gmail_writer": self.mock_gmail_writer,
                "gmail_reader": self.mock_gmail_reader,
                "approval_handler": self.mock_approval_handler,
            },
        )

        with patch("openai.OpenAI") as mock_openai:
            self.agent = Agent(self.agent_schema)
            self.mock_openai_client = mock_openai.return_value
