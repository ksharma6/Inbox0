import uuid

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


def register_flask_routes(app, workflow):
    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError):
        return (
            jsonify({"error": "invalid_request", "details": error.errors()}),
            400,
        )

    @app.route("/start_workflow", methods=["POST"])
    def start_workflow():
        req = StartWorkflowRequest.model_validate(request.get_json(silent=True) or {})

        thread_id = str(uuid.uuid4())
        initial_state = GmailAgentState(user_id=req.user_id, thread_id=thread_id)

        result_gen = workflow.workflow.stream(initial_state)

        for state in result_gen:
            if isinstance(state, dict):
                actual_state = extract_langgraph_state(state)
                state = GmailAgentState(**actual_state)

            if state.awaiting_approval:
                save_state_to_store(state)
                return jsonify({"status": "paused", "awaiting_approval": True})
            final_state = state

        save_state_to_store(final_state)
        return jsonify({"status": "completed", "workflow_complete": final_state.workflow_complete})

    @app.route("/resume_workflow", methods=["POST"])
    def resume_workflow():
        req = ResumeWorkflowRequest.model_validate(request.get_json(silent=True) or {})

        state = load_state_from_store(req.user_id)

        if state is None:
            return (
                jsonify(
                    {
                        "error": "no_paused_workflow",
                        "message": f"No saved workflow state found for user_id={req.user_id}",
                    }
                ),
                404,
            )

        if isinstance(state, dict):
            actual_state = extract_langgraph_state(state)
            state = GmailAgentState(**actual_state)

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
        return jsonify({"status": "resumed", "workflow_complete": final_state.workflow_complete})
