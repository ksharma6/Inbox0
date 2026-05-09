from unittest.mock import patch

import pytest
from pydantic import ValidationError
from src.models.agent_schemas import AgentSchema, GmailAgentState


def test_agent_schema_uses_openrouter_api_key():
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "openrouter-key"}, clear=True):
        schema = AgentSchema()

    assert schema.api_key == "openrouter-key"


def test_agent_schema_uses_openai_api_key_fallback():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "openai-key"}, clear=True):
        schema = AgentSchema()

    assert schema.api_key == "openai-key"


def test_agent_schema_requires_api_key():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValidationError, match="No API key found"):
            AgentSchema()


def test_agent_schema_rejects_blank_api_key():
    with pytest.raises(ValidationError, match="No API key found"):
        AgentSchema(api_key="   ")


def test_agent_schema_defaults_app_name_to_inbox0():
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "openrouter-key"}, clear=True):
        schema = AgentSchema()

    assert schema.app_name == "Inbox0"


def test_gmail_agent_state_uses_workflow_run_id_not_thread_id():
    state = GmailAgentState(user_id="U090QS5DDEE", workflow_run_id="workflow-run-123")

    assert state.workflow_run_id == "workflow-run-123"
    assert not hasattr(state, "thread_id")


def test_gmail_agent_state_rejects_legacy_thread_id_without_workflow_run_id():
    with pytest.raises(ValidationError) as exc_info:
        GmailAgentState(user_id="U090QS5DDEE", thread_id="legacy-thread-id")

    assert any(err["loc"] == ("workflow_run_id",) for err in exc_info.value.errors())
