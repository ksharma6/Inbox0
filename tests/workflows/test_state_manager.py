from src.models.agent_schemas import GmailAgentState
from src.workflows.state_manager import StateManager

VALID_SLACK_USER_ID = "U12345678"
VALID_GMAIL_ACCOUNT_ID = "gmail-account-123"


def test_memory_store_keys_state_by_workflow_run_id_not_user_id():
    state_manager = StateManager(storage_backend="memory")
    first_run = GmailAgentState(
        gmail_account_id=VALID_GMAIL_ACCOUNT_ID,
        slack_user_id=VALID_SLACK_USER_ID,
        workflow_run_id="workflow-run-1",
    )
    second_run = GmailAgentState(
        gmail_account_id=VALID_GMAIL_ACCOUNT_ID,
        slack_user_id=VALID_SLACK_USER_ID,
        workflow_run_id="workflow-run-2",
    )

    state_manager.save_state(first_run)
    state_manager.save_state(second_run)

    assert state_manager.load_state("workflow-run-1") == first_run
    assert state_manager.load_state("workflow-run-2") == second_run


def test_memory_store_does_not_fall_back_to_user_id_for_unknown_workflow_run():
    state_manager = StateManager(storage_backend="memory")
    state = GmailAgentState(
        gmail_account_id=VALID_GMAIL_ACCOUNT_ID,
        slack_user_id=VALID_SLACK_USER_ID,
        workflow_run_id="workflow-run-1",
    )

    state_manager.save_state(state)

    assert state_manager.load_state("hallucinated-workflow-run") is None
    assert state_manager.load_state(VALID_SLACK_USER_ID) is None
