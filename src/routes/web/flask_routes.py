from dataclasses import dataclass
from hmac import compare_digest
from os import getenv

from flask import jsonify, request
from pydantic import ValidationError
from src.models.agent_schemas import WorkflowResultStatus, WorkflowRunResult
from src.routes.web.schemas import ResumeWorkflowRequest, StartWorkflowRequest

API_KEY_HEADER = "X-Inbox0-API-Key"


@dataclass(frozen=True)
class AuthenticatedWorkflowUser:
    gmail_account_id: str
    slack_user_id: str


def _authenticate_workflow_request():
    expected_api_key = getenv("INBOX0_API_KEY")
    gmail_account_id = getenv("INBOX0_GMAIL_ACCOUNT_ID")
    slack_user_id = getenv("INBOX0_SLACK_USER_ID")

    if not expected_api_key or not gmail_account_id or not slack_user_id:
        return None, (jsonify({"error": "auth_not_configured"}), 500)

    supplied_api_key = request.headers.get(API_KEY_HEADER)
    if not supplied_api_key or not compare_digest(supplied_api_key, expected_api_key):
        return None, (jsonify({"error": "unauthorized"}), 401)

    return AuthenticatedWorkflowUser(gmail_account_id=gmail_account_id, slack_user_id=slack_user_id), None


def _result_to_response(result: WorkflowRunResult):
    """Translate a WorkflowRunResult into a Flask (json, http_status) response.

    Single mapping point between the workflow's typed result and the JSON wire
    format. New result statuses get one new branch here and nowhere else.
    """
    if result.status is WorkflowResultStatus.NOT_FOUND:
        return (
            jsonify({"error": "no_paused_workflow", "message": result.error_message}),
            404,
        )
    if result.status is WorkflowResultStatus.FORBIDDEN:
        return jsonify({"error": "forbidden"}), 403
    if result.status is WorkflowResultStatus.PAUSED:
        return jsonify(
            {
                "status": "paused",
                "awaiting_approval": True,
                "workflow_run_id": result.workflow_run_id,
            }
        )
    return jsonify(
        {
            "status": "completed",
            "workflow_complete": result.workflow_complete,
            "workflow_run_id": result.workflow_run_id,
        }
    )


def register_flask_routes(app, workflow):
    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError):
        return (
            jsonify({"error": "invalid_request", "details": error.errors()}),
            400,
        )

    @app.route("/start_workflow", methods=["POST"])
    def start_workflow():
        authenticated_user, auth_error = _authenticate_workflow_request()
        if auth_error:
            return auth_error

        StartWorkflowRequest.model_validate(request.get_json(silent=True) or {})

        result = workflow.start(
            authenticated_user.gmail_account_id,
            authenticated_user.slack_user_id,
        )
        return _result_to_response(result)

    @app.route("/resume_workflow", methods=["POST"])
    def resume_workflow():
        authenticated_user, auth_error = _authenticate_workflow_request()
        if auth_error:
            return auth_error

        req = ResumeWorkflowRequest.model_validate(request.get_json(silent=True) or {})

        result = workflow.resume(
            req.workflow_run_id,
            authenticated_user.gmail_account_id,
            req.action,
        )
        return _result_to_response(result)
