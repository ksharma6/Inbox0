import unittest
from unittest.mock import MagicMock, patch

import httpx
from openai import APIConnectionError
from src.agent.agent import Agent
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
from src.models.agent_schemas import AgentSchema
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler
from tenacity import wait_none


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

    def test_create_chat_completion_retries_transient_failure(self):
        """Transient OpenAI/OpenRouter-compatible errors are retried."""
        expected_response = MagicMock()
        transient_error = APIConnectionError(
            message="temporary connection failure",
            request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
        )
        self.agent.client = MagicMock()
        create = self.agent.client.chat.completions.create
        create.side_effect = [transient_error, expected_response]

        result = self.agent._create_chat_completion.retry_with(wait=wait_none())(
            self.agent,
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        self.assertEqual(result, expected_response)
        self.assertEqual(create.call_count, 2)
