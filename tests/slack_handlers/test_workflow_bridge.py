from src.models.agent_schemas import GmailAgentState
from src.slack_handlers import workflow_bridge


def test_resume_workflow_after_action_warns_when_workflow_run_id_missing(mocker):
    respond = mocker.Mock()
    workflow = mocker.Mock()
    load_state = mocker.patch.object(workflow_bridge, "load_state_from_store")

    workflow_bridge.resume_workflow_after_action(None, respond, workflow)

    load_state.assert_not_called()
    workflow.workflow.stream.assert_not_called()
    respond.assert_called_once_with(":warning: Could not resume workflow: missing workflow run ID.")


def test_resume_workflow_after_action_warns_when_saved_state_missing(mocker):
    respond = mocker.Mock()
    workflow = mocker.Mock()
    load_state = mocker.patch.object(workflow_bridge, "load_state_from_store", return_value=None)

    workflow_bridge.resume_workflow_after_action("workflow-run-123", respond, workflow)

    load_state.assert_called_once_with("workflow-run-123")
    workflow.workflow.stream.assert_not_called()
    respond.assert_called_once_with(":warning: Could not resume workflow: saved state was not found.")


def test_resume_workflow_after_action_streams_and_saves_final_state(mocker):
    respond = mocker.Mock()
    workflow = mocker.Mock()
    saved_state = GmailAgentState(
        gmail_account_id="gmail-account-123",
        slack_user_id="U12345678",
        workflow_run_id="workflow-run-123",
        awaiting_approval=True,
    )
    final_state = saved_state.model_copy(update={"awaiting_approval": False, "workflow_complete": True})
    load_state = mocker.patch.object(workflow_bridge, "load_state_from_store", return_value=saved_state)
    save_state = mocker.patch.object(workflow_bridge, "save_state_to_store")
    workflow.workflow.stream.return_value = [final_state]

    workflow_bridge.resume_workflow_after_action("workflow-run-123", respond, workflow)

    load_state.assert_called_once_with("workflow-run-123")
    workflow.workflow.stream.assert_called_once()
    streamed_state = workflow.workflow.stream.call_args.args[0]
    assert streamed_state.awaiting_approval is False
    assert streamed_state.current_draft_index == 1
    save_state.assert_called_once_with(final_state)
    respond.assert_called_once_with("✅ Workflow completed successfully!")
