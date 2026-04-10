import logging

from flask import jsonify, request
from slack_bolt import App as SlackApp
from src.slack_handlers.workflow_bridge import resume_workflow_after_action


def register_slack_routes(app, slack_app: SlackApp, workflow):
    @slack_app.action("approve_draft")
    def approve_draft_action(ack, body, respond):
        logging.info("approve_draft_action payload=%s", body)
        # Handle action via shared workflow's DraftApprovalHandler
        workflow.draft_handler.handle_approval_action(ack, body, respond)

        # After handling the draft action, resume the workflow
        user_id = body["user"]["id"]
        resume_workflow_after_action(user_id, respond, workflow)

    @slack_app.action("reject_draft")
    def reject_draft_action(ack, body, respond):
        logging.info("reject_draft_action payload=%s", body)
        workflow.draft_handler.handle_approval_action(ack, body, respond)
        user_id = body["user"]["id"]
        resume_workflow_after_action(user_id, respond, workflow)

    @slack_app.action("save_draft")
    def save_draft_action(ack, body, respond):
        logging.info("save_draft_action payload=%s", body)
        workflow.draft_handler.handle_approval_action(ack, body, respond)
        user_id = body["user"]["id"]
        resume_workflow_after_action(user_id, respond, workflow)

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
                import json

                payload = json.loads(request.form["payload"])
                logging.info("Parsed payload: %s", payload)
                if "actions" in payload and payload["actions"]:
                    action = payload["actions"][0]
                    action_id = action.get("action_id")
                    logging.info("Action ID: %s", action_id)
                    if action_id == "approve_draft":
                        approve_draft_action(
                            lambda: None,
                            payload,
                            lambda text: logging.info("Response: %s", text),
                        )
                        return jsonify({"response_action": "ack"})
                    elif action_id == "reject_draft":
                        reject_draft_action(
                            lambda: None,
                            payload,
                            lambda text: logging.info("Response: %s", text),
                        )
                        return jsonify({"response_action": "ack"})
                    elif action_id == "save_draft":
                        save_draft_action(
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
