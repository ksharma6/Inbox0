"""Tests for Flask web route authentication and request validation."""

from unittest.mock import patch

import pytest
from flask import Flask
from pydantic import ValidationError
from src.models.agent_schemas import GmailAgentState
from src.routes.web.flask_routes import API_KEY_HEADER, register_flask_routes
from src.routes.web.schemas import ResumeAction, ResumeWorkflowRequest, StartWorkflowRequest

VALID_API_KEY = "test-api-key"
VALID_GMAIL_ACCOUNT_ID = "gmail-account-123"
OTHER_GMAIL_ACCOUNT_ID = "gmail-account-456"
VALID_SLACK_USER_ID = "U12345678"
VALID_WORKFLOW_RUN_ID = "workflow-run-123"

AUTH_ENV = {
    "INBOX0_API_KEY": VALID_API_KEY,
    "INBOX0_GMAIL_ACCOUNT_ID": VALID_GMAIL_ACCOUNT_ID,
    "INBOX0_SLACK_USER_ID": VALID_SLACK_USER_ID,
}


def _auth_headers(api_key: str = VALID_API_KEY):
    """Return auth headers for protected workflow route requests."""
    return {API_KEY_HEADER: api_key}


def _make_client(mocker):
    """Build a Flask test client with the routes registered against a mock workflow."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    workflow = mocker.Mock()
    register_flask_routes(app, workflow)
    return app.test_client(), workflow


class TestStartWorkflowRequestSchema:
    def test_accepts_empty_payload(self):
        """Start payload carries no identity; auth supplies Gmail and Slack IDs."""
        assert StartWorkflowRequest().model_dump() == {}

    @pytest.mark.parametrize("field", ["user_id", "slack_user_id", "gmail_account_id"])
    def test_rejects_client_supplied_identity_fields(self, field):
        """Clients must not supply identity or Slack routing fields in the body."""
        with pytest.raises(ValidationError):
            StartWorkflowRequest.model_validate({field: "spoofed"})


class TestResumeWorkflowRequestSchema:
    def test_accepts_valid_payload(self):
        """Resume payload only needs workflow_run_id and action."""
        req = ResumeWorkflowRequest(workflow_run_id=VALID_WORKFLOW_RUN_ID, action="approve_draft")

        assert req.workflow_run_id == VALID_WORKFLOW_RUN_ID
        assert req.action is ResumeAction.APPROVE_DRAFT

    @pytest.mark.parametrize(
        "action_value,expected",
        [
            ("approve_draft", ResumeAction.APPROVE_DRAFT),
            ("reject_draft", ResumeAction.REJECT_DRAFT),
            ("save_draft", ResumeAction.SAVE_DRAFT),
        ],
    )
    def test_accepts_each_resume_action(self, action_value, expected):
        """All supported resume actions validate to the enum."""
        req = ResumeWorkflowRequest(workflow_run_id=VALID_WORKFLOW_RUN_ID, action=action_value)
        assert req.action is expected

    def test_rejects_unknown_action(self):
        """Unknown resume actions are rejected before workflow state changes."""
        with pytest.raises(ValidationError):
            ResumeWorkflowRequest(workflow_run_id=VALID_WORKFLOW_RUN_ID, action="delete_everything")

    @pytest.mark.parametrize("field", ["user_id", "slack_user_id", "gmail_account_id"])
    def test_rejects_client_supplied_identity_fields(self, field):
        """Resume requests cannot spoof owner or routing identity."""
        with pytest.raises(ValidationError):
            ResumeWorkflowRequest.model_validate(
                {
                    "workflow_run_id": VALID_WORKFLOW_RUN_ID,
                    "action": "approve_draft",
                    field: "spoofed",
                }
            )


class TestWorkflowRouteAuth:
    def test_missing_api_key_returns_401(self, mocker):
        """Protected workflow routes require X-Inbox0-API-Key."""
        client, workflow = _make_client(mocker)

        with patch.dict("os.environ", AUTH_ENV):
            response = client.post("/start_workflow", json={})

        assert response.status_code == 401
        assert response.get_json()["error"] == "unauthorized"
        workflow.workflow.stream.assert_not_called()

    def test_invalid_api_key_returns_401(self, mocker):
        """Invalid API keys cannot start workflows."""
        client, workflow = _make_client(mocker)

        with patch.dict("os.environ", AUTH_ENV):
            response = client.post("/start_workflow", json={}, headers=_auth_headers("wrong-key"))

        assert response.status_code == 401
        assert response.get_json()["error"] == "unauthorized"
        workflow.workflow.stream.assert_not_called()

    def test_missing_auth_config_returns_500(self, mocker):
        """Server must be configured with API key, Gmail account ID, and Slack user ID."""
        client, workflow = _make_client(mocker)

        with patch.dict("os.environ", {}, clear=True):
            response = client.post("/start_workflow", json={}, headers=_auth_headers())

        assert response.status_code == 500
        assert response.get_json()["error"] == "auth_not_configured"
        workflow.workflow.stream.assert_not_called()


class TestStartWorkflowRoute:
    def test_rejects_spoofed_identity_fields(self, mocker):
        """Body-supplied identity fields are rejected even with valid auth."""
        client, workflow = _make_client(mocker)

        with patch.dict("os.environ", AUTH_ENV):
            response = client.post(
                "/start_workflow",
                json={"user_id": "attacker", "gmail_account_id": OTHER_GMAIL_ACCOUNT_ID},
                headers=_auth_headers(),
            )

        assert response.status_code == 400
        assert response.get_json()["error"] == "invalid_request"
        workflow.workflow.stream.assert_not_called()

    def test_completed_response_includes_workflow_run_id(self, mocker):
        """Start route builds state from verified API-key mapping."""
        client, workflow = _make_client(mocker)
        mocker.patch("src.routes.web.flask_routes.uuid.uuid4", return_value=VALID_WORKFLOW_RUN_ID)
        save_state = mocker.patch("src.routes.web.flask_routes.save_state_to_store")
        workflow.workflow.stream.return_value = [
            {
                "done": {
                    "gmail_account_id": VALID_GMAIL_ACCOUNT_ID,
                    "slack_user_id": VALID_SLACK_USER_ID,
                    "workflow_run_id": VALID_WORKFLOW_RUN_ID,
                }
            },
        ]

        with patch.dict("os.environ", AUTH_ENV):
            response = client.post("/start_workflow", json={}, headers=_auth_headers())

        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "completed"
        assert body["workflow_run_id"] == VALID_WORKFLOW_RUN_ID
        initial_state = workflow.workflow.stream.call_args.args[0]
        assert initial_state.gmail_account_id == VALID_GMAIL_ACCOUNT_ID
        assert initial_state.slack_user_id == VALID_SLACK_USER_ID
        save_state.assert_called_once()

    def test_paused_response_includes_workflow_run_id(self, mocker):
        """Paused start responses still return the workflow_run_id for later resume."""
        client, workflow = _make_client(mocker)
        mocker.patch("src.routes.web.flask_routes.uuid.uuid4", return_value=VALID_WORKFLOW_RUN_ID)
        save_state = mocker.patch("src.routes.web.flask_routes.save_state_to_store")
        workflow.workflow.stream.return_value = [
            {
                "paused": {
                    "gmail_account_id": VALID_GMAIL_ACCOUNT_ID,
                    "slack_user_id": VALID_SLACK_USER_ID,
                    "workflow_run_id": VALID_WORKFLOW_RUN_ID,
                    "awaiting_approval": True,
                }
            },
        ]

        with patch.dict("os.environ", AUTH_ENV):
            response = client.post("/start_workflow", json={}, headers=_auth_headers())

        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "paused"
        assert body["awaiting_approval"] is True
        assert body["workflow_run_id"] == VALID_WORKFLOW_RUN_ID
        save_state.assert_called_once()


class TestResumeWorkflowRoute:
    def test_invalid_action_returns_400(self, mocker):
        """Invalid actions are rejected before loading or mutating workflow state."""
        client, workflow = _make_client(mocker)

        with patch.dict("os.environ", AUTH_ENV):
            response = client.post(
                "/resume_workflow",
                json={"workflow_run_id": VALID_WORKFLOW_RUN_ID, "action": "delete_everything"},
                headers=_auth_headers(),
            )

        assert response.status_code == 400
        body = response.get_json()
        assert body["error"] == "invalid_request"
        assert any(err["loc"] == ["action"] for err in body["details"])
        workflow.workflow.stream.assert_not_called()

    def test_returns_404_when_no_paused_workflow(self, mocker):
        """Unknown workflow_run_id returns 404 after request auth succeeds."""
        client, workflow = _make_client(mocker)
        load_state = mocker.patch("src.routes.web.flask_routes.load_state_from_store", return_value=None)

        with patch.dict("os.environ", AUTH_ENV):
            response = client.post(
                "/resume_workflow",
                json={"workflow_run_id": VALID_WORKFLOW_RUN_ID, "action": "approve_draft"},
                headers=_auth_headers(),
            )

        assert response.status_code == 404
        body = response.get_json()
        assert body["error"] == "no_paused_workflow"
        assert VALID_WORKFLOW_RUN_ID in body["message"]
        load_state.assert_called_once_with(VALID_WORKFLOW_RUN_ID)
        workflow.workflow.stream.assert_not_called()

    def test_cross_gmail_account_resume_returns_403(self, mocker):
        """A valid API key cannot resume workflow state owned by another Gmail account."""
        client, workflow = _make_client(mocker)
        saved_state = GmailAgentState(
            gmail_account_id=OTHER_GMAIL_ACCOUNT_ID,
            slack_user_id=VALID_SLACK_USER_ID,
            workflow_run_id=VALID_WORKFLOW_RUN_ID,
            awaiting_approval=True,
        )
        mocker.patch("src.routes.web.flask_routes.load_state_from_store", return_value=saved_state)
        save_state = mocker.patch("src.routes.web.flask_routes.save_state_to_store")

        with patch.dict("os.environ", AUTH_ENV):
            response = client.post(
                "/resume_workflow",
                json={"workflow_run_id": VALID_WORKFLOW_RUN_ID, "action": "approve_draft"},
                headers=_auth_headers(),
            )

        assert response.status_code == 403
        assert response.get_json()["error"] == "forbidden"
        workflow.workflow.stream.assert_not_called()
        save_state.assert_not_called()
