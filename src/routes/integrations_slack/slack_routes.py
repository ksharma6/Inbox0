import json
import logging

from flask import jsonify, request
from pydantic import ValidationError
from slack_bolt import App as SlackApp
from src.routes.integrations_slack.schemas import SlackActionBody
from src.slack_handlers.workflow_bridge import resume_workflow_after_action

INVALID_PAYLOAD_USER_MESSAGE = (
    ":warning: Could not process this action — Slack sent an unexpected "
    "payload. Please check application logs (error code: `SLACK_PAYLOAD_INVALID`)."
)


def _parse_slack_action(body, event_name):
    """Validate a Slack action payload.

    Returns the parsed ``SlackActionBody`` on success, or ``None`` on
    failure. On failure, logs at ``WARNING`` with the
    ``[SLACK_PAYLOAD_INVALID]`` token plus the originating ``event_name``
    so operators can grep across log files for a specific handler.
    """
    try:
        return SlackActionBody.model_validate(body)
    except ValidationError as exc:
        logging.warning(
            "[SLACK_PAYLOAD_INVALID] event=%s errors=%s raw_keys=%s",
            event_name,
            exc.errors(),
            list(body.keys()) if isinstance(body, dict) else type(body).__name__,
        )
        return None


def register_slack_routes(app, slack_app: SlackApp, workflow):
    @slack_app.action("approve_draft")
    def approve_draft_action(ack, body, respond):
        logging.info("approve_draft_action payload=%s", body)

        parsed = _parse_slack_action(body, "approve_draft_action")
        if parsed is None:
            ack()
            respond(text=INVALID_PAYLOAD_USER_MESSAGE)
            return

        workflow.draft_handler.handle_approval_action(ack, body, respond)
        resume_workflow_after_action(parsed.user.id, respond, workflow)

    @slack_app.action("reject_draft")
    def reject_draft_action(ack, body, respond):
        logging.info("reject_draft_action payload=%s", body)

        parsed = _parse_slack_action(body, "reject_draft_action")
        if parsed is None:
            ack()
            respond(text=INVALID_PAYLOAD_USER_MESSAGE)
            return

        workflow.draft_handler.handle_approval_action(ack, body, respond)
        resume_workflow_after_action(parsed.user.id, respond, workflow)

    @slack_app.action("save_draft")
    def save_draft_action(ack, body, respond):
        logging.info("save_draft_action payload=%s", body)

        parsed = _parse_slack_action(body, "save_draft_action")
        if parsed is None:
            ack()
            respond(text=INVALID_PAYLOAD_USER_MESSAGE)
            return

        workflow.draft_handler.handle_approval_action(ack, body, respond)
        resume_workflow_after_action(parsed.user.id, respond, workflow)

    action_dispatch = {
        "approve_draft": approve_draft_action,
        "reject_draft": reject_draft_action,
        "save_draft": save_draft_action,
    }

    @app.route("/slack/events", methods=["POST"])
    def slack_events():
        logging.info("Received Slack event request")

        content_type = request.headers.get("Content-Type", "")

        if "application/json" in content_type and request.json:
            logging.info("slack_events payload=%s", request.json)
            logging.info("Processing JSON request")
            if request.json.get("type") == "url_verification":
                challenge = request.json.get("challenge", "")
                return challenge, 200

        if "application/x-www-form-urlencoded" in content_type and request.form:
            logging.info("Processing form data: %s", dict(request.form))
            if "payload" in request.form:
                try:
                    payload = json.loads(request.form["payload"])
                except json.JSONDecodeError as exc:
                    logging.warning(
                        "[SLACK_PAYLOAD_INVALID] event=slack_events_form errors=json_decode raw=%s",
                        exc,
                    )
                    return jsonify({"error": "invalid_payload"}), 400

                logging.info("Parsed payload: %s", payload)

                parsed = _parse_slack_action(payload, "slack_events_form")
                if parsed is None:
                    return jsonify({"error": "invalid_payload"}), 400

                action_id = parsed.actions[0].action_id
                logging.info("Action ID: %s", action_id)

                handler_fn = action_dispatch.get(action_id)
                if handler_fn is not None:
                    handler_fn(
                        lambda: None,
                        payload,
                        lambda text: logging.info("Response: %s", text),
                    )
                    return jsonify({"response_action": "ack"})

        try:
            from slack_bolt.adapter.flask import SlackRequestHandler

            handler = SlackRequestHandler(slack_app)
            return handler.handle(request)
        except Exception as e:
            import traceback

            logging.error("Full traceback: %s", traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/slack/actions", methods=["POST"])
    def slack_actions():
        logging.info("Received Slack action request")

        if request.form:
            logging.info("Form data: %s", dict(request.form))
            payload = request.form.get("payload", "{}")
            logging.info("Payload: %s", payload)

        try:
            from slack_bolt.adapter.flask import SlackRequestHandler

            handler = SlackRequestHandler(slack_app)
            return handler.handle(request)
        except Exception as e:
            logging.error("Error in slack_app handler for actions: %s", e)
            import traceback

            logging.error("Full traceback: %s", traceback.format_exc())
            return jsonify({"error": str(e)}), 500
