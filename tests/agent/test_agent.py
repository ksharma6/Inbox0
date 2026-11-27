import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from openai import APIConnectionError
from src.agent.agent import Agent
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
from src.models.agent_schemas import AgentSchema, ProcessRequestSchema
from src.models.gmail import GmailReaderToolFunction
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler
from tenacity import wait_none


class TestAgent(unittest.TestCase):
    """Test suite for the Agent class"""

    def setUp(self):
        """Set up the test environment by:
        1. Creating mock objects for GmailWriter, GmailReader, and DraftApprovalHandler.
        2. Creating an AgentSchema that registers those mocks as the Agent's tools.
        3. Building the real read_emails ToolFunction schema for tests that offer tools.
        4. Patching OpenAI in src.agent.agent and creating an Agent instance, so the
           Agent's client is the mock stored in self.mock_openai_client.
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

        self.read_emails_schema = GmailReaderToolFunction.generate_read_emails_schema()

        with (
            patch("src.agent.agent.OpenAI") as mock_openai,
            patch("src.agent.agent.UsageTracker") as mock_usagetracker,
        ):
            self.agent = Agent(self.agent_schema)
            self.mock_usage_tracker = mock_usagetracker.return_value
            self.mock_openai_client = mock_openai.return_value

    def test_initialization(self):
        """Test that Agent initializes with schema and available tools."""
        assert self.agent.schema == self.agent_schema

        assert self.mock_openai_client is self.agent.client
        assert self.mock_usage_tracker is self.agent.usage_tracker

        assert "create_draft" in self.agent.function_map
        assert "read_emails" in self.agent.function_map
        assert "send_draft_for_approval" in self.agent.function_map

        # Verify methods are correctly mapped to their specific handlers
        assert self.agent.function_map["create_draft"] is self.mock_gmail_writer.create_draft
        assert self.agent.function_map["read_emails"] is self.mock_gmail_reader.read_emails
        assert (
            self.agent.function_map["send_draft_for_approval"]
            is self.mock_draft_approval_handler.send_draft_for_approval
        )

    def test_create_chat_completion_retries_transient_failure(self):
        """Transient OpenAI/OpenRouter-compatible errors are retried."""
        expected_response = MagicMock()
        transient_error = APIConnectionError(
            message="temporary connection failure",
            request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
        )
        create = self.mock_openai_client.chat.completions.create
        create.side_effect = [transient_error, expected_response]

        result = self.agent._create_chat_completion.retry_with(wait=wait_none())(
            self.agent,
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        assert result == expected_response
        assert create.call_count == 2

    def test_openrouter_chat_completion_privacy(self):
        """OpenRouter requests require ZDR and deny provider data collection."""
        self.agent.schema.base_url = "https://openrouter.ai/api/v1"
        expected_response = self.mock_openai_client.chat.completions.create.return_value

        messages = [{"role": "user", "content": "hello"}]
        result = self.agent._create_chat_completion(model="test-model", messages=messages)

        assert result == expected_response

        create_completion = self.mock_openai_client.chat.completions.create

        create_completion.assert_called_once_with(
            model="test-model",
            messages=messages,
            extra_body={
                "provider": {
                    "zdr": True,
                    "data_collection": "deny",
                }
            },
        )

    def test_non_openrouter_chat_completion_omits_openrouter_fields(self):
        """Non-OpenRouter requests do not receive OpenRouter-specific fields"""
        self.agent.schema.base_url = "http://localhost:11434/v1"
        messages = [{"role": "user", "content": "hello"}]
        self.agent._create_chat_completion(model="test-model", messages=messages)
        create_completion = self.mock_openai_client.chat.completions.create
        create_completion.assert_called_once_with(model="test-model", messages=messages)

    @patch("src.agent.agent.tiktoken")
    def test_estimate_prompt_tokens_uses_model_encoding(self, mock_tiktoken):
        """Use the model-specific tokenizer when the model has a known encoding."""
        encoder = mock_tiktoken.encoding_for_model.return_value
        encoder.encode.side_effect = lambda x: list(x)

        messages = [{"role": "system", "content": "hello world"}, {"role": "system", "content": None}]

        total = self.agent._estimate_prompt_tokens(messages=messages)

        assert total == 11
        mock_tiktoken.encoding_for_model.assert_called_once_with(self.agent.schema.model)
        mock_tiktoken.get_encoding.assert_not_called()

    @patch("src.agent.agent.tiktoken")
    def test_estimate_prompt_tokens_uses_cl100k_base_encoding(self, mock_tiktoken):
        """Fall back to the cl100k_base tokenizer for an unknown model."""
        mock_tiktoken.encoding_for_model.side_effect = KeyError()
        encoder = mock_tiktoken.get_encoding.return_value
        encoder.encode.side_effect = lambda x: list(x)

        messages = [{"role": "system", "content": "hello world"}, {"role": "system", "content": None}]

        total = self.agent._estimate_prompt_tokens(messages=messages)
        assert total == 11

        mock_tiktoken.get_encoding.assert_called_once_with("cl100k_base")
        mock_tiktoken.encoding_for_model.assert_called()

    @staticmethod
    def _make_tool_call(tool_call_id, name, arguments="{}"):
        """Build a one-element list of fake tool calls shaped like an OpenAI response.

        Args:
            tool_call_id (str): ID assigned to the tool call, echoed back in the tool message.
            name (str): Name of the function the model is requesting.
            arguments (str): JSON-encoded arguments string. Defaults to "{}".

        Returns:
            list[SimpleNamespace]: A list containing a single tool call with `id` and
                `function.name` / `function.arguments` attributes.
        """
        return [SimpleNamespace(id=tool_call_id, function=SimpleNamespace(name=name, arguments=arguments))]

    @staticmethod
    def _make_response(content, tool_calls):
        """Build a fake chat completion response with a single choice.

        Args:
            content (str): Assistant message content.
            tool_calls (Optional[list[SimpleNamespace]]): Tool calls attached to the
                message, or None for a response with no tool calls.

        Returns:
            SimpleNamespace: An object exposing `choices[0].message.content` and
                `choices[0].message.tool_calls`.
        """
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=content,
                        tool_calls=tool_calls,
                    )
                )
            ]
        )

    @patch("src.agent.agent.Agent._timed_completion")
    def test_process_request_returns_content_when_no_tool_calls(self, mock_timed_completion):
        """Return the assistant content when the response has no tool calls."""
        mock_response = self._make_response(content="Final answer", tool_calls=None)

        mock_timed_completion.return_value = mock_response

        no_tools_schema = ProcessRequestSchema(
            user_prompt="test user_prompt", llm_tool_schema=None, system_message="test system_message"
        )

        final_response = self.agent.process_request(no_tools_schema)

        assert final_response == "Final answer"
        assert mock_timed_completion.call_count == 1

    @patch("src.agent.agent.Agent._timed_completion")
    def test_max_iterations_terminates_tool_calls(self, mock_timed_completion):
        """Return the final response when processing reaches its iteration limit."""
        mock_timed_completion.side_effect = [
            self._make_response(
                content="",
                tool_calls=self._make_tool_call(tool_call_id="01", name="read_emails"),
            ),
            self._make_response(content="Final response", tool_calls=None),
        ]

        tools_schema = ProcessRequestSchema(
            user_prompt="test user_prompt",
            llm_tool_schema=self.read_emails_schema,
            system_message="test system_message",
        )

        final_response = self.agent.process_request(tools_schema, max_iterations=1)

        calls = mock_timed_completion.call_args_list
        loop_call = calls[0].kwargs
        final_call = calls[-1].kwargs

        assert loop_call["tools"]
        assert loop_call["tool_choice"] == "auto"

        assert final_call.get("tools") is None
        assert final_call.get("tool_choice") is None

        assert final_response == "Final response"
        assert mock_timed_completion.call_count == 2

    @patch("src.agent.agent.Agent._timed_completion")
    def test_unknown_tool_names_create_informative_tool_response(self, mock_timed_completion):
        """Append a 'not available' tool message when the model requests an unregistered function."""
        mock_final_response = self._make_response(
            content="", tool_calls=self._make_tool_call(tool_call_id="01", name="gmail_wr1ter")
        )

        mock_timed_completion.return_value = mock_final_response

        tools_schema = ProcessRequestSchema(
            user_prompt="test user_prompt", llm_tool_schema=None, system_message="test system_message"
        )

        self.agent.process_request(tools_schema, max_iterations=1)

        last_call = mock_timed_completion.call_args
        messages = last_call.kwargs["messages"]
        tool_message = next(m for m in messages if isinstance(m, dict) and m.get("role") == "tool")

        assert "is not available" in tool_message["content"]
        assert tool_message["name"] == "gmail_wr1ter"

    @patch("src.agent.agent.Agent._timed_completion")
    def test_read_email_invoked_with_invalid_json(self, mock_timed_completion):
        """Call read_emails when its arguments string is not valid JSON."""
        mock_response = self._make_response(
            content="",
            tool_calls=self._make_tool_call(
                tool_call_id="01", name="read_emails", arguments="{silly_name: very wrong json lol}"
            ),
        )

        mock_timed_completion.return_value = mock_response
        self.mock_gmail_reader.read_emails.return_value = "<email>"

        tools_schema = ProcessRequestSchema(
            user_prompt="test user_prompt", llm_tool_schema=None, system_message="test system_message"
        )

        self.agent.process_request(tools_schema, max_iterations=1)
        last_call = mock_timed_completion.call_args
        messages = last_call.kwargs["messages"]
        tool_message = next(m for m in messages if isinstance(m, dict) and m.get("role") == "tool")

        assert tool_message["tool_call_id"] == "01"
        assert tool_message["name"] == "read_emails"

        assert tool_message["content"] == "<email>"

        self.mock_gmail_reader.read_emails.assert_called_once_with()

    @patch("src.agent.agent.Agent._timed_completion")
    def test_invalid_json_args_produce_expected_tool_error_response(self, mock_timed_completion):
        """Append an invalid-arguments tool message and skip the handler when arguments are not valid JSON."""
        mock_final_response = self._make_response(
            content="",
            tool_calls=self._make_tool_call(
                tool_call_id="01", name="send_draft_for_approval", arguments="{invalid_json}"
            ),
        )

        tools_schema = ProcessRequestSchema(
            user_prompt="test user_prompt", llm_tool_schema=None, system_message="test system_message"
        )
        mock_timed_completion.return_value = mock_final_response
        self.agent.process_request(tools_schema, max_iterations=1)

        last_call = mock_timed_completion.call_args
        messages = last_call.kwargs["messages"]
        tool_message = next(m for m in messages if isinstance(m, dict) and m.get("role") == "tool")

        assert "Error: Invalid arguments for " in tool_message["content"]
        assert tool_message["name"] == "send_draft_for_approval"
        self.mock_draft_approval_handler.send_draft_for_approval.assert_not_called()

    @patch("src.agent.agent.Agent._timed_completion")
    def test_send_draft_for_approval_rejects_empty_draft(self, mock_timed_completion):
        """Append a draft-required tool message and skip the handler when the draft is empty."""
        mock_final_response = self._make_response(
            content="",
            tool_calls=self._make_tool_call(
                tool_call_id="01", name="send_draft_for_approval", arguments='{"draft": ""}'
            ),
        )

        mock_timed_completion.return_value = mock_final_response

        tool_schema = ProcessRequestSchema(
            user_prompt="test prompt", llm_tool_schema=None, system_message="test system_message"
        )

        self.agent.process_request(tool_schema, max_iterations=1)

        last_call = mock_timed_completion.call_args
        messages = last_call.kwargs["messages"]
        tool_message = next(m for m in messages if isinstance(m, dict) and m.get("role") == "tool")

        assert "Error: send_draft_for_approval requires a draft object." in tool_message["content"]
        self.mock_draft_approval_handler.send_draft_for_approval.assert_not_called()

    @patch("src.agent.agent.Agent._timed_completion")
    def test_tool_arg_typeerror_converts_into_error_response(self, mock_timed_completion):
        """Append an argument-mismatch tool message when the tool raises TypeError."""
        mock_final_response = self._make_response(
            content="", tool_calls=self._make_tool_call(tool_call_id="01", name="create_draft")
        )

        mock_timed_completion.return_value = mock_final_response
        self.mock_gmail_writer.create_draft.side_effect = TypeError

        tools_schema = ProcessRequestSchema(
            user_prompt="test user_prompt", llm_tool_schema=None, system_message="test system_message"
        )

        self.agent.process_request(tools_schema, max_iterations=1)

        last_call = mock_timed_completion.call_args
        messages = last_call.kwargs["messages"]

        tool_message = next(m for m in messages if isinstance(m, dict) and m.get("role") == "tool")
        assert "Error: Could not call create_draft due to argument mismatch." in tool_message["content"]
        self.mock_gmail_writer.create_draft.assert_called_once()

    @patch("src.agent.agent.Agent._timed_completion")
    def test_valid_tool_call_dispatches_decoded_args(self, mock_timed_completion):
        """Call the tool with JSON-decoded keyword arguments and append its result as the tool message."""
        mock_final_response = self._make_response(
            content="",
            tool_calls=self._make_tool_call(
                tool_call_id="01",
                name="create_draft",
                arguments='{"sender": "test", "recipient": "test", "subject": "test", "message": "test"}',
            ),
        )

        mock_timed_completion.return_value = mock_final_response
        self.mock_gmail_writer.create_draft.return_value = "<draft>"

        tools_schema = ProcessRequestSchema(
            user_prompt="test user_prompt", llm_tool_schema=None, system_message="test system_message"
        )

        self.agent.process_request(tools_schema, max_iterations=1)

        last_call = mock_timed_completion.call_args
        messages = last_call.kwargs["messages"]
        tool_message = next(m for m in messages if isinstance(m, dict) and m.get("role") == "tool")

        self.mock_gmail_writer.create_draft.assert_called_once_with(
            sender="test", recipient="test", subject="test", message="test"
        )

        assert tool_message["content"] == "<draft>"

    @patch("src.agent.agent.Agent._timed_completion")
    def test_multi_tool_call_preserves_message_history(self, mock_timed_completion):
        """Keep every tool message, in order, across multiple tool-calling iterations."""
        mock_timed_completion.side_effect = [
            self._make_response("", self._make_tool_call(tool_call_id="01", name="read_emails")),
            self._make_response("", self._make_tool_call(tool_call_id="02", name="create_draft")),
            self._make_response("Done", None),
        ]

        tools_schema = ProcessRequestSchema(
            user_prompt="test user_prompt", llm_tool_schema=None, system_message="test system_message"
        )

        result = self.agent.process_request(tools_schema, max_iterations=5)

        last_call = mock_timed_completion.call_args

        messages = last_call.kwargs["messages"]
        tool_messages = [m for m in messages if isinstance(m, dict) and m.get("role") == "tool"]

        tools = [("read_emails", "01"), ("create_draft", "02")]

        assert len(tools) == len(tool_messages)

        for tool, tool_message in zip(tools, tool_messages):
            assert tool[0] == tool_message["name"]
            assert tool[1] == tool_message["tool_call_id"]

        assert mock_timed_completion.call_count == 3
        assert result == "Done"
