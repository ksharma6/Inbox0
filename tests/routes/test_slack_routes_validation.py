"""Tests for the Slack routes module.

Covers:
- ``_parse_slack_action`` helper: valid, malformed, and non-dict inputs.
- ``slack_events`` form-encoded path: malformed JSON, malformed shape,
  and successful dispatch into the registered action handlers.
- ``slack_events`` JSON path: ``url_verification`` challenge.

The action handlers (``approve_draft_action`` etc.) are defined as closures
inside ``register_slack_routes`` and registered with the Slack Bolt app via
``@slack_app.action(...)``. We exercise them indirectly via the
form-encoded ``/slack/events`` dispatch path, which is also one of the
production entry points and therefore the most realistic surface to test.
"""

import json
import logging

import pytest
from flask import Flask
from src.routes.integrations_slack import slack_routes as slack_routes_module
from src.routes.integrations_slack.slack_routes import (
    _parse_slack_action,
    register_slack_routes,
)

VALID_SLACK_USER_ID = "U090QS5DDEE"


def _valid_action_body(action_id="approve_draft", value=None):
    """Minimal Slack action body that passes ``SlackActionBody`` validation."""
    return {
        "user": {"id": VALID_SLACK_USER_ID, "name": "kishen"},
        "team": {"id": "T123", "domain": "example"},
        "actions": [
            {
                "action_id": action_id,
                "value": value or f"{action_id.split('_')[0]}_draft-abc-123",
                "type": "button",
            }
        ],
    }


def _passthrough_action_decorator(*_args, **_kwargs):
    """Mimics ``slack_app.action(...)`` so the registered handler is preserved.

    A bare ``Mock()`` would replace each handler with another Mock, so calling
    ``approve_draft_action`` from the dispatch dict would no-op. This shim
    behaves like the real Slack Bolt decorator: it returns the function
    unchanged so it can still be invoked from ``slack_events``.
    """

    def decorator(fn):
        return fn

    return decorator


def _make_client(mocker):
    """Build a Flask test client with Slack routes registered against mocks."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    slack_app = mocker.Mock()
    slack_app.action = _passthrough_action_decorator
    workflow = mocker.Mock()

    register_slack_routes(app, slack_app, workflow)
    return app.test_client(), slack_app, workflow


class TestParseSlackAction:
    def test_returns_model_for_valid_payload(self):
        parsed = _parse_slack_action(_valid_action_body(), "unit_test")
        assert parsed is not None
        assert parsed.user.id == VALID_SLACK_USER_ID
        assert parsed.actions[0].action_id == "approve_draft"

    def test_ignores_extra_fields(self):
        parsed = _parse_slack_action(_valid_action_body(), "unit_test")
        assert not hasattr(parsed, "team")
        assert not hasattr(parsed.user, "name")

    @pytest.mark.parametrize(
        "mutation,description",
        [
            (lambda b: b.pop("user"), "missing_user"),
            (lambda b: b.pop("actions"), "missing_actions"),
            (lambda b: b["user"].pop("id"), "missing_user_id"),
            (lambda b: b.__setitem__("actions", []), "empty_actions"),
            (lambda b: b["actions"][0].pop("value"), "missing_action_value"),
            (lambda b: b["actions"][0].pop("action_id"), "missing_action_id"),
        ],
    )
    def test_returns_none_and_logs_on_invalid_payload(self, caplog, mutation, description):
        body = _valid_action_body()
        mutation(body)

        with caplog.at_level(logging.WARNING):
            result = _parse_slack_action(body, "unit_test")

        assert result is None
        assert "[SLACK_PAYLOAD_INVALID]" in caplog.text
        assert "event=unit_test" in caplog.text

    def test_returns_none_for_non_dict_body(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _parse_slack_action("not a dict", "unit_test")

        assert result is None
        assert "[SLACK_PAYLOAD_INVALID]" in caplog.text


class TestSlackEventsFormPath:
    def _post_form_payload(self, client, payload_obj):
        """POST a form-encoded Slack interactive payload to /slack/events."""
        return client.post(
            "/slack/events",
            data={"payload": json.dumps(payload_obj) if not isinstance(payload_obj, str) else payload_obj},
            content_type="application/x-www-form-urlencoded",
        )

    def test_invalid_json_returns_400_and_logs(self, caplog, mocker):
        client, _, _ = _make_client(mocker)

        with caplog.at_level(logging.WARNING):
            response = client.post(
                "/slack/events",
                data={"payload": "{not valid json"},
                content_type="application/x-www-form-urlencoded",
            )

        assert response.status_code == 400
        assert response.get_json() == {"error": "invalid_payload"}
        assert "[SLACK_PAYLOAD_INVALID]" in caplog.text
        assert "event=slack_events_form" in caplog.text
        assert "errors=json_decode" in caplog.text

    def test_invalid_payload_shape_returns_400_and_logs(self, caplog, mocker):
        client, _, _ = _make_client(mocker)

        with caplog.at_level(logging.WARNING):
            response = self._post_form_payload(client, {"actions": []})

        assert response.status_code == 400
        assert response.get_json() == {"error": "invalid_payload"}
        assert "[SLACK_PAYLOAD_INVALID]" in caplog.text
        assert "event=slack_events_form" in caplog.text

    @pytest.mark.parametrize(
        "action_id",
        ["approve_draft", "reject_draft", "save_draft"],
    )
    def test_valid_payload_dispatches_to_workflow(self, mocker, action_id):
        resume_mock = mocker.patch.object(slack_routes_module, "resume_workflow_after_action")
        client, _, workflow = _make_client(mocker)

        response = self._post_form_payload(client, _valid_action_body(action_id=action_id))

        assert response.status_code == 200
        assert response.get_json() == {"response_action": "ack"}
        workflow.draft_handler.handle_approval_action.assert_called_once()
        resume_mock.assert_called_once()
        # The user_id passed to resume must come from the parsed model, not raw indexing.
        called_user_id = resume_mock.call_args.args[0]
        assert called_user_id == VALID_SLACK_USER_ID

    def test_unknown_action_id_falls_through_to_handler(self, mocker):
        # A valid-shaped body with an unknown action_id should NOT dispatch to
        # one of our handlers and falls through to the SlackRequestHandler
        # adapter. We mock the adapter so we can assert on the fallthrough.
        adapter_mock = mocker.Mock()
        adapter_mock.handle.return_value = ("", 200)
        mocker.patch(
            "slack_bolt.adapter.flask.SlackRequestHandler",
            return_value=adapter_mock,
        )
        resume_mock = mocker.patch.object(slack_routes_module, "resume_workflow_after_action")
        client, _, workflow = _make_client(mocker)

        response = self._post_form_payload(client, _valid_action_body(action_id="open_modal"))

        assert response.status_code == 200
        workflow.draft_handler.handle_approval_action.assert_not_called()
        resume_mock.assert_not_called()
        adapter_mock.handle.assert_called_once()


class TestSlackEventsJsonPath:
    def test_url_verification_returns_challenge(self, mocker):
        client, _, _ = _make_client(mocker)

        response = client.post(
            "/slack/events",
            json={"type": "url_verification", "challenge": "abc123"},
        )

        assert response.status_code == 200
        assert response.get_data(as_text=True) == "abc123"
