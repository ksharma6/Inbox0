from src.models.toolfunction import ParamProperties, ToolFunction, ToolParams


class SlackToolFunction:
    """
    Defines TooFunction schema for sending emails drafts to slack for review and approval
    """

    @staticmethod
    def generate_send_draft_for_approval_schema() -> ToolFunction:
        """
        Returns Pydantic ToolFunction for `SlackGmailBridge.send_draft_for_approval()`
        """
        return ToolFunction(
            name="send_draft_for_approval",
            description=(
                "Sends a draft email for approval with interactive buttons in Slack. "
                "IMPORTANT: You must call create_draft() FIRST to get the draft object, "
                "then pass that draft here."
            ),
            parameters=ToolParams(
                type="object",
                properties={
                    "draft": ParamProperties(
                        type="object",
                        description="The Gmail draft dictionary returned from create_draft() function",
                    ),
                    "user_id": ParamProperties(
                        type="string",
                        description="Slack user ID to send approval request to",
                    ),
                    "channel_id": ParamProperties(
                        type="string",
                        description="Optional channel ID (if not provided, sends DM)",
                    ),
                },
                required=["draft", "user_id"],
            ),
        )
