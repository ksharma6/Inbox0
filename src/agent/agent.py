import json
import logging
import time
from typing import Callable, Dict

import tiktoken
from openai import OpenAI
from openai.types.chat import ChatCompletion
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
from src.models.agent_schemas import AgentSchema, ProcessRequestSchema
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler
from src.utils.usage_tracker import UsageTracker

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, schema: AgentSchema):
        """Initializes OpenRouter agent using OpenRouter SDK and schema configuration defined by
        agent_schemas.py

        Args:
            schema (AgentSchema): Configuration schema containing API key, model, site_url, app_name, and
            available tools
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
                self.function_map["send_draft_for_approval"] = instance.send_draft_for_approval
            else:
                logger.error(f"Unknown tool type: {type(instance)} for tool: {tool_name}")

    def _estimate_prompt_tokens(self, messages: list[dict]) -> int:
        """
        Estimates the number of tokens across all messages before sending to LLM.
        Uses cl100k_base as fallback for non-OpenAI models routed via OpenRouter.
        """
        try:
            encoding = tiktoken.encoding_for_model(self.schema.model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")

        total = 0

        for message in messages:
            content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
            if content and isinstance(content, str):
                total += len(encoding.encode(content))
        return total

    def _timed_completion(self, label: str, **kwargs) -> ChatCompletion:
        """Wraps chat.completions.create with pre-flight token estimation and duration logging"""
        est_tokens = self._estimate_prompt_tokens(kwargs.get("messages", []))
        logger.info(
            "LLM request sent",
            extra={
                "event": "llm_request",
                "step": label,
                "model": self.schema.model,
                "estimated_prompt_tokens": est_tokens,
            },
        )
        t0 = time.perf_counter()
        response = self.client.chat.completions.create(**kwargs)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        usage = response.usage
        tps = (usage.completion_tokens / (elapsed_ms / 1000)) if elapsed_ms > 0 else 0
        logger.info(
            "LLM response received",
            extra={
                "event": "llm_response",
                "step": label,
                "model": self.schema.model,
                "elapsed_ms": round(elapsed_ms, 1),
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.prompt_tokens + usage.completion_tokens,
                "output_tok_per_s": round(tps, 1),
            },
        )
        self.usage_tracker.log_usage(
            model=self.schema.model,
            site_url=self.site_url,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )
        return response

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
            response = self._timed_completion(
                f"iteration_{iteration + 1}",
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
                    logger.info("Function arguments: %s", function_args_str)

                    function_to_call = self.function_map.get(function_name)

                    if function_to_call:
                        # Handle missing keys in function_args if they are optional
                        try:
                            function_args = json.loads(function_args_str)

                            # Special handling for Slack functions that need draft
                            if function_name in ["send_draft_for_approval"]:
                                if "draft" not in function_args or not function_args["draft"]:
                                    result = (
                                        f"Error: {function_name} requires a draft object. "
                                        "You must call create_draft() first to get a draft, "
                                        "then pass that draft to this function."
                                    )
                                else:
                                    result = function_to_call(**function_args)
                            else:
                                result = function_to_call(**function_args)

                        except TypeError as e:
                            logger.error(f"Error calling {function_name} with args {function_args_str}: {e}")
                            result = f"Error: Could not call {function_name} due to argument mismatch."
                        except json.JSONDecodeError:
                            logger.error(
                                f"Error decoding arguments for {function_name}. "
                                "Trying to call without arguments or with defaults."
                            )
                            # Attempt to call with no args if appropriate, or handle default
                            if function_name == "read_emails":  # Example: read_emails might default
                                result = function_to_call()
                            else:
                                result = f"Error: Invalid arguments for {function_name}."

                        logger.info("Tool '%s' executed. Result: %s", function_name, result)
                        messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": str(result),  # Ensure content is a string
                            }
                        )
                    else:
                        logger.error("Unknown function '%s' requested by LLM.", function_name)
                        logger.error("Available functions: %s", list(self.function_map.keys()))
                        messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": f"Error: Function '{function_name}' is not available. Available functions:\
                                     {list(self.function_map.keys())}",
                            }
                        )

                # Continue to next iteration for more tool calls
                iteration += 1

            else:
                # No more tool calls, get final response
                final_response = response_message.content
                logger.info("Agent final response (no more tools needed):\n%s", final_response)
                return final_response

        # If we reach max iterations, get a final response
        logger.info("Reached maximum iterations (%s). Getting final response...", max_iterations)
        final_response_obj = self._timed_completion("final_max_iterations", model=self.schema.model, messages=messages)
        final_response = final_response_obj.choices[0].message.content
        logger.info("Agent final response:\n%s", final_response)
        return final_response
