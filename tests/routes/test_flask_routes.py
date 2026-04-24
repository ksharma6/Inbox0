"""Tests for the Flask web routes and their request schemas.

Covers:
- ``StartWorkflowRequest`` / ``ResumeWorkflowRequest`` pydantic validation
  (Slack user-id format, required fields, enum-bound action).
- ``/start_workflow`` returns 400 on schema-invalid payloads via the
  ``ValidationError`` handler.
- ``/resume_workflow`` returns 404 when no paused state exists for the
  given user_id (guard against the previous ``AttributeError`` on
  ``NoneType``).
"""

import pytest
from flask import Flask
from pydantic import ValidationError
from src.routes.web.flask_routes import register_flask_routes
from src.routes.web.schemas import (
    ResumeAction,
    ResumeWorkflowRequest,
    StartWorkflowRequest,
)

VALID_SLACK_USER_ID = "U090QS5DDEE"


def _make_client(mocker):
    """Build a Flask test client with the routes registered against a mock workflow."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    workflow = mocker.Mock()
    register_flask_routes(app, workflow)
    return app.test_client(), workflow


class TestStartWorkflowRequestSchema:
    def test_accepts_valid_slack_user_id(self):
        req = StartWorkflowRequest(user_id=VALID_SLACK_USER_ID)
        assert req.user_id == VALID_SLACK_USER_ID

    @pytest.mark.parametrize(
        "bad_user_id",
        [
            "",
            "test-user-123",
            "u090qs5ddee",
            "U short",
            "X090QS5DDEE",
            "U123",
        ],
    )
    def test_rejects_invalid_user_id(self, bad_user_id):
        with pytest.raises(ValidationError):
            StartWorkflowRequest(user_id=bad_user_id)

    def test_rejects_missing_user_id(self):
        with pytest.raises(ValidationError):
            StartWorkflowRequest()


class TestResumeWorkflowRequestSchema:
    def test_accepts_valid_payload(self):
        req = ResumeWorkflowRequest(user_id=VALID_SLACK_USER_ID, action="approve_draft")
        assert req.user_id == VALID_SLACK_USER_ID
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
        req = ResumeWorkflowRequest(user_id=VALID_SLACK_USER_ID, action=action_value)
        assert req.action is expected

    def test_rejects_unknown_action(self):
        with pytest.raises(ValidationError):
            ResumeWorkflowRequest(user_id=VALID_SLACK_USER_ID, action="delete_everything")

    def test_rejects_invalid_user_id(self):
        with pytest.raises(ValidationError):
            ResumeWorkflowRequest(user_id="test-user-123", action="approve_draft")


class TestStartWorkflowRoute:
    def test_invalid_user_id_returns_400(self, mocker):
        client, workflow = _make_client(mocker)

        response = client.post("/start_workflow", json={"user_id": "test-user-123"})

        assert response.status_code == 400
        body = response.get_json()
        assert body["error"] == "invalid_request"
        assert any(err["loc"] == ["user_id"] for err in body["details"])
        workflow.workflow.stream.assert_not_called()

    def test_missing_body_returns_400(self, mocker):
        client, workflow = _make_client(mocker)

        response = client.post("/start_workflow", json={})

        assert response.status_code == 400
        assert response.get_json()["error"] == "invalid_request"
        workflow.workflow.stream.assert_not_called()


class TestResumeWorkflowRoute:
    def test_invalid_action_returns_400(self, mocker):
        client, workflow = _make_client(mocker)

        response = client.post(
            "/resume_workflow",
            json={"user_id": VALID_SLACK_USER_ID, "action": "delete_everything"},
        )

        assert response.status_code == 400
        body = response.get_json()
        assert body["error"] == "invalid_request"
        assert any(err["loc"] == ["action"] for err in body["details"])
        workflow.workflow.stream.assert_not_called()

    def test_returns_404_when_no_paused_workflow(self, mocker):
        client, workflow = _make_client(mocker)
        mocker.patch(
            "src.routes.web.flask_routes.load_state_from_store",
            return_value=None,
        )

        response = client.post(
            "/resume_workflow",
            json={"user_id": VALID_SLACK_USER_ID, "action": "approve_draft"},
        )

        assert response.status_code == 404
        body = response.get_json()
        assert body["error"] == "no_paused_workflow"
        assert VALID_SLACK_USER_ID in body["message"]
        workflow.workflow.stream.assert_not_called()
