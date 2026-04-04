import json
import logging
from typing import Callable, Dict

from openai import OpenAI
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
from src.models.agent_schemas import AgentSchema, ProcessRequestSchema
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler
from src.utils.usage_tracker import UsageTracker

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, schema: AgentSchema):
        """Initializes OpenRouter agent using OpenRouter SDK and schema configuration defined by agent_schemas.py

        Args:
            schema (AgentSchema): Configuration schema containing API key, model, site_url, app_name, and available tools
        """
        self.schema = schema
        self.available_tools = schema.available_tools
        self.function_map: Dict[str, Callable] = {}
        self.site_url = schema.site_url
        self.usage_tracker = UsageTracker()
        self.client = OpenAI(
            api_key=schema.api_key,
            base_url=schema.base_url,
            default_headers={
                "HTTP-Referer": schema.site_url,
                "X-Title": schema.app_name,
            },
        )
        # Map available tools to their methods
        self._setup_function_map()

    def _setup_function_map(self):
        """Setup the function mapping based on available tools"""
        if not self.available_tools:
            return
        for tool_name, instance in self.available_tools.items():
            if isinstance(instance, GmailWriter):
                # Map GmailWriter methods to function names
                self.function_map["create_draft"] = instance.create_draft
                self.function_map["send_draft"] = instance.send_draft
                self.function_map["save_draft"] = instance.save_draft
                self.function_map["send_reply"] = instance.send_reply
            elif isinstance(instance, GmailReader):
                # Map GmailReader methods to function names
                self.function_map["read_emails"] = instance.read_emails
            elif isinstance(instance, DraftApprovalHandler):
                # Map DraftApprovalHandler methods to function names
                self.function_map["send_draft_for_approval"] = (
                    instance.send_draft_for_approval
                )
            else:
                logger.error(
                    f"Unknown tool type: {type(instance)} for tool: {tool_name}"
                )

    def process_request(self, schema: ProcessRequestSchema, max_iterations: int = 5):
        """Processes user's request by interacting with OpenAI model.

        Args:
            schema (ProcessRequestSchema): Request schema containing user prompt, tool schema, and system message
            max_iterations (int): Maximum number of tool call rounds (default: 5)

        Returns:
            str: The final response from the agent
        """
        self.llm_tool_schema = schema.llm_tool_schema
        self.user_prompt = schema.user_prompt

        messages = []
        if schema.system_message:
            messages.append({"role": "system", "content": schema.system_message})
        messages.append({"role": "user", "content": schema.user_prompt})

        logger.info("Prompt received: %s", schema.user_prompt)
        logger.info("Tool schema: %s", schema.llm_tool_schema)

        logger.info("Messages: %s", messages)

        # Convert tool schema(s) to proper OpenAI format
        # Handle both single ToolFunction and list of ToolFunctions
        tools_payload = None  # Default to None
        if schema.llm_tool_schema:  # Only process if not None
            if isinstance(schema.llm_tool_schema, list):
                tools_payload = [
                    {
                        "type": "function",
                        "function": tool_schema.model_dump(),
                    }
                    for tool_schema in schema.llm_tool_schema
                ]
            else:
                tools_payload = [
                    {
                        "type": "function",
                        "function": schema.llm_tool_schema.model_dump(),
                    }
                ]

        iteration = 0
        while iteration < max_iterations:
            logger.info("--- Iteration %s/%s ---", iteration + 1, max_iterations)
            response = self.client.chat.completions.create(
                model=self.schema.model,
                messages=messages,
                tools=tools_payload,
                tool_choice="auto" if tools_payload else None,
            )
            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls

            if tool_calls:
                logger.info("Agent decided to use %s tool(s).", len(tool_calls))
                logger.info("Tool calls: %s", tool_calls)

                # add agent's reply
                messages.append(response_message)
                logger.info("Messages after agent's reply: %s", messages)

                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args_str = tool_call.function.arguments

                    logger.info("Function to call: %s", function_name)
                    print(f"Function arguments: {function_args_str}")

                    function_to_call = self.function_map.get(function_name)

                    if function_to_call:
                        # Handle missing keys in function_args if they are optional
                        try:
                            function_args = json.loads(function_args_str)

                            # Special handling for Slack functions that need draft
                            if function_name in ["send_draft_for_approval"]:
                                if (
                                    "draft" not in function_args
                                    or not function_args["draft"]
                                ):
                                    result = f"Error: {function_name} requires a draft object. You must call create_draft() first to get a draft, then pass that draft to this function."
                                else:
                                    result = function_to_call(**function_args)
                            else:
                                result = function_to_call(**function_args)

                        except TypeError as e:
                            print(
                                f"Error calling {function_name} with args {function_args_str}: {e}"
                            )
                            result = f"Error: Could not call {function_name} due to argument mismatch."
                        except json.JSONDecodeError:
                            print(
                                f"Error decoding arguments for {function_name}. Trying to call without arguments or with defaults."
                            )
                            # Attempt to call with no args if appropriate, or handle default
                            if (
                                function_name == "read_emails"
                            ):  # Example: read_emails might default
                                result = function_to_call()
                            else:
                                result = (
                                    f"Error: Invalid arguments for {function_name}."
                                )

                        print(f"Tool '{function_name}' executed. Result: {result}")
                        messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": str(result),  # Ensure content is a string
                            }
                        )
                    else:
                        print(f"Unknown function '{function_name}' requested by LLM.")
                        print(f"Available functions: {list(self.function_map.keys())}")
                        messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": f"Error: Function '{function_name}' is not available. Available functions: {list(self.function_map.keys())}",
                            }
                        )

                # Continue to next iteration for more tool calls
                iteration += 1

            else:
                # No more tool calls, get final response
                final_response = response_message.content
                print(
                    f"\nAgent final response (no more tools needed):\n{final_response}"
                )
                return final_response

        # If we reach max iterations, get a final response
        print(
            f"\nReached maximum iterations ({max_iterations}). Getting final response..."
        )
        final_response = (
            self.client.chat.completions.create(
                model=self.schema.model, messages=messages
            )
            .choices[0]
            .message.content
        )
        print(f"\nAgent final response:\n{final_response}")

        # extract + log usage data
        usage_data = response.usage

        self.usage_tracker.log_usage(
            model=self.schema.model,
            site_url=self.site_url,
            prompt_tokens=usage_data.prompt_tokens,
            completion_tokens=usage_data.completion_tokens,
            # total_tokens=usage_data.total_tokens,
        )
        return final_response
