import unittest
from unittest.mock import MagicMock, patch

from src.agent.agent import Agent
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
from src.models.agent_schemas import AgentSchema
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
                "approval_handler": self.mock_draft_approval_handler,
            },
        )

        with patch("openai.OpenAI") as mock_openai:
            self.agent = Agent(self.agent_schema)
            self.mock_openai_client = mock_openai.return_value

    def test_initialization(self):
        """Test that Agent initializes with schema and available tools."""
        self.assertEqual(self.agent.schema, self.agent_schema)

        self.assertIn("create_draft", self.agent.function_map)
        self.assertIn("read_emails", self.agent.function_map)
        self.assertIn("send_draft_for_approval", self.agent.function_map)

        # Verify methods are correctly mapped to their specific handlers
        self.assertEqual(self.agent.function_map["create_draft"], self.mock_gmail_writer.create_draft)
        self.assertEqual(self.agent.function_map["read_emails"], self.mock_gmail_reader.read_emails)
        self.assertEqual(
            self.agent.function_map["send_draft_for_approval"],
            self.mock_draft_approval_handler.send_draft_for_approval,
        )
