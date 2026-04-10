import uuid

from flask import jsonify, request
from src.models.agent_schemas import GmailAgentState
from src.workflows.state_manager import (
    extract_langgraph_state,
    load_state_from_store,
    save_state_to_store,
)


def register_flask_routes(app, workflow):
    @app.route("/start_workflow", methods=["POST"])
    def start_workflow():
        # Extract user_id from the POST request JSON body
        user_id = request.json["user_id"]

        # Generate a unique thread ID for this workflow run
        thread_id = str(uuid.uuid4())

        # Create initial workflow state with user and thread IDs
        initial_state = GmailAgentState(user_id=user_id, thread_id=thread_id)

        # Start the workflow execution as a generator, yielding states at each step
        result_gen = workflow.workflow.stream(initial_state)

        # Iterate through each state yielded by the workflow
        for state in result_gen:
            # Handle both dict and GmailAgentState objects
            if isinstance(state, dict):
                # LangGraph returns nested dict structure, extract the actual state
                actual_state = extract_langgraph_state(state)
                state = GmailAgentState(**actual_state)

            # Check for pause condition
            if state.awaiting_approval:  # Check if workflow is waiting for human approval
                save_state_to_store(state)  # Save the current state to persistent storage so it can be resumed later
                return jsonify(
                    {"status": "paused", "awaiting_approval": True}
                )  # Return HTTP response indicating workflow is paused
            final_state = state  # Store the current state as final_state (will be overwritten in each iteration)

        # Save the final state after workflow completes all steps
        save_state_to_store(final_state)
        return jsonify(
            {"status": "completed", "workflow_complete": final_state.workflow_complete}
        )  # Return HTTP response with completion status

    @app.route("/resume_workflow", methods=["POST"])
    def resume_workflow():
        user_id = request.json["user_id"]
        action = request.json["action"]  # e.g., 'approve' or 'reject'
        state = load_state_from_store(user_id)

        # Ensure state is a GmailAgentState object
        if isinstance(state, dict):
            # LangGraph returns nested dict structure, extract the actual state
            actual_state = extract_langgraph_state(state)
            state = GmailAgentState(**actual_state)

        # Update state based on Slack action
        state.awaiting_approval = False

        if action == "approve_draft":
            # Keep the current draft and move to next
            state.current_draft_index += 1
            print(f"User approved draft {state.current_draft_index - 1}")
        elif action == "reject_draft":
            # Use the draft handler to reject the draft
            if state.draft_responses and state.current_draft_index < len(state.draft_responses):
                # The DraftApprovalHandler will handle the rejection logic
                print(f"User rejected draft {state.current_draft_index}")
            state.current_draft_index += 1
        elif action == "save_draft":
            # Save the current draft
            print(f"User saved draft {state.current_draft_index}")
            state.current_draft_index += 1
        else:
            print(f"Unknown action: {action}, continuing workflow")
            state.current_draft_index += 1

        result_gen = workflow.workflow.stream(state)
        for new_state in result_gen:
            # Ensure new_state is a GmailAgentState object
            if isinstance(new_state, dict):
                # LangGraph returns nested dict structure, extract the actual state
                actual_state = extract_langgraph_state(new_state)
                new_state = GmailAgentState(**actual_state)
            final_state = new_state
        save_state_to_store(final_state)
        return jsonify({"status": "resumed", "workflow_complete": final_state.workflow_complete})
