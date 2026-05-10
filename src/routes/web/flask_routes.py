import uuid
from dataclasses import dataclass
from hmac import compare_digest
from os import getenv

from flask import jsonify, request
from pydantic import ValidationError
from src.models.agent_schemas import GmailAgentState
from src.routes.web.schemas import (
    ResumeAction,
    ResumeWorkflowRequest,
    StartWorkflowRequest,
)
from src.workflows.state_manager import (
    extract_langgraph_state,
    load_state_from_store,
    save_state_to_store,
)

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

        workflow_run_id = str(uuid.uuid4())
        initial_state = GmailAgentState(
            gmail_account_id=authenticated_user.gmail_account_id,
            slack_user_id=authenticated_user.slack_user_id,
            workflow_run_id=workflow_run_id,
        )

        result_gen = workflow.workflow.stream(initial_state)

        for state in result_gen:
            if isinstance(state, dict):
                actual_state = extract_langgraph_state(state)
                state = GmailAgentState(**actual_state)

            if state.awaiting_approval:
                save_state_to_store(state)
                return jsonify(
                    {
                        "status": "paused",
                        "awaiting_approval": True,
                        "workflow_run_id": state.workflow_run_id,
                    }
                )
            final_state = state

        save_state_to_store(final_state)
        return jsonify(
            {
                "status": "completed",
                "workflow_complete": final_state.workflow_complete,
                "workflow_run_id": final_state.workflow_run_id,
            }
        )

    @app.route("/resume_workflow", methods=["POST"])
    def resume_workflow():
        authenticated_user, auth_error = _authenticate_workflow_request()
        if auth_error:
            return auth_error

        req = ResumeWorkflowRequest.model_validate(request.get_json(silent=True) or {})

        state = load_state_from_store(req.workflow_run_id)

        if state is None:
            return (
                jsonify(
                    {
                        "error": "no_paused_workflow",
                        "message": f"No saved workflow state found for workflow_run_id={req.workflow_run_id}",
                    }
                ),
                404,
            )

        if isinstance(state, dict):
            actual_state = extract_langgraph_state(state)
            state = GmailAgentState(**actual_state)

        if state.gmail_account_id != authenticated_user.gmail_account_id:
            return jsonify({"error": "forbidden"}), 403

        state.awaiting_approval = False

        if req.action is ResumeAction.APPROVE_DRAFT:
            state.current_draft_index += 1
            print(f"User approved draft {state.current_draft_index - 1}")
        elif req.action is ResumeAction.REJECT_DRAFT:
            if state.draft_responses and state.current_draft_index < len(state.draft_responses):
                print(f"User rejected draft {state.current_draft_index}")
            state.current_draft_index += 1
        elif req.action is ResumeAction.SAVE_DRAFT:
            print(f"User saved draft {state.current_draft_index}")
            state.current_draft_index += 1

        result_gen = workflow.workflow.stream(state)
        for new_state in result_gen:
            if isinstance(new_state, dict):
                actual_state = extract_langgraph_state(new_state)
                new_state = GmailAgentState(**actual_state)
            final_state = new_state
        save_state_to_store(final_state)
        return jsonify(
            {
                "status": "resumed",
                "workflow_complete": final_state.workflow_complete,
                "workflow_run_id": final_state.workflow_run_id,
            }
        )
