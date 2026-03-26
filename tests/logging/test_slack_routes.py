import logging
from unittest.mock import MagicMock, patch

from flask import Flask
from src.routes.integrations_slack.slack_routes import register_slack_routes


def test_register_slack_routes(caplog, mocker):
    """Test that the register_slack_routes function logs the correct information when a Slack event is received.

    Args:
        caplog (pytest.LogCaptureFixture): The caplog fixture.
        mocker (pytest_mock.MockerFixture): The mocker fixture.
    """
    app = Flask(__name__)
    slack_app = mocker.Mock()
    workflow = mocker.Mock()

    register_slack_routes(app, slack_app, workflow)

    client = app.test_client()

    mock_handler = MagicMock()
    mock_handler.handle.return_value = ("", 200)
    with patch(
        "slack_bolt.adapter.flask.SlackRequestHandler", return_value=mock_handler
    ):
        with caplog.at_level(logging.INFO):
            client.post(
                "/slack/events",
                json={"type": "event_callback", "foo": "bar"},
                headers={"Content-Type": "application/json"},
            )
    assert "Received Slack event request" in caplog.text
    assert "slack_events payload=" in caplog.text
    assert "Processing JSON request" in caplog.text
