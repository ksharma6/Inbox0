"""Pydantic schemas for incoming Slack interaction payloads.

These narrow the validation surface for Slack action callbacks (button
clicks on draft approval messages). Slack payloads contain ~30 fields so ``extra="ignore"``
discards the rest. To inspect more fields (debugging or new features), switch to ``extra="allow"``.

Logging convention: Validation failures must be logged with the token ``[SLACK_PAYLOAD_INVALID]``
so they can be grepped easily across log files when debugging user-reported issues, e.g.::

    grep SLACK_PAYLOAD_INVALID logs/*.log
"""

from pydantic import BaseModel, ConfigDict, Field


class SlackUser(BaseModel):
    """Subset of the Slack ``user`` object included in action payloads."""

    model_config = ConfigDict(extra="ignore")

    id: str


class SlackAction(BaseModel):
    """A single action element from a Slack interactive component click."""

    model_config = ConfigDict(extra="ignore")

    action_id: str
    value: str


class SlackActionBody(BaseModel):
    """Top-level Slack action body posted when a user clicks a button.

    Only fields read by ``DraftApprovalHandler`` and the action route
    handlers are declared. Everything else (team, channel, container,
    message, response_url, ...) is ignored to keep the model focused.

    ``actions`` requires at least one element so the common
    ``actions[0]`` access elsewhere never raises ``IndexError`` -- the
    validator catches that case at the boundary.
    """

    model_config = ConfigDict(extra="ignore")

    user: SlackUser
    actions: list[SlackAction] = Field(..., min_length=1)
