"""
Tests for EmailProcessingWorkflow.start() / .resume() and their private helpers.

These are the public-API tests for the orchestration centralization (issue #80).
They mock workflow.workflow.stream (the compiled LangGraph) and patch the state
store at the workflow module level, so no real LangGraph or persistence is
exercised. Per-node behavior is covered by other test files.

Coverage:
- _coerce_state: pass-through, nested-dict unwrap, unsupported types
- _apply_resume_action: approve, reject, save, defensive unknown-action branch
- start: paused vs. completed result, persistence on both, fresh workflow_run_id
- resume: not_found, forbidden, action paths, persistence, awaiting_approval reset
"""

from unittest.mock import patch

import pytest
from src.agent.agent import Agent
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
from src.models.agent_schemas import (
    GmailAgentState,
    WorkflowResultStatus,
    WorkflowRunResult,
)
from src.routes.web.schemas import ResumeAction
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler
from src.workflows.workflow import EmailProcessingWorkflow

GMAIL_ACCOUNT_ID = "gmail-account-123"
OTHER_GMAIL_ACCOUNT_ID = "gmail-account-other"
SLACK_USER_ID = "U12345678"
WORKFLOW_RUN_ID = "wf-run-fixed"


def _make_state(
    *,
    gmail_account_id: str = GMAIL_ACCOUNT_ID,
    slack_user_id: str = SLACK_USER_ID,
    workflow_run_id: str = WORKFLOW_RUN_ID,
    awaiting_approval: bool = False,
    workflow_complete: bool = False,
    current_draft_index: int = 0,
    draft_responses: list | None = None,
) -> GmailAgentState:
    """Build a GmailAgentState with sensible test defaults."""
    return GmailAgentState(
        gmail_account_id=gmail_account_id,
        slack_user_id=slack_user_id,
        workflow_run_id=workflow_run_id,
        awaiting_approval=awaiting_approval,
        workflow_complete=workflow_complete,
        current_draft_index=current_draft_index,
        draft_responses=draft_responses or [],
    )


@pytest.fixture
def workflow(mocker):
    """EmailProcessingWorkflow with all external deps mocked and the compiled
    LangGraph replaced with a Mock so .stream(...) is scriptable per test."""
    gmail_reader = mocker.Mock(spec=GmailReader)
    gmail_writer = mocker.Mock(spec=GmailWriter)
    draft_handler = mocker.Mock(spec=DraftApprovalHandler)
    agent = mocker.Mock(spec=Agent)

    with patch("openai.OpenAI"):
        wf = EmailProcessingWorkflow(
            gmail_reader=gmail_reader,
            gmail_writer=gmail_writer,
            draft_handler=draft_handler,
            agent=agent,
        )

    wf.workflow = mocker.Mock()
    return wf


class TestCoerceState:
    """_coerce_state normalizes LangGraph's three emission shapes."""

    def test_passes_gmail_agent_state_through_unchanged(self, workflow):
        state = _make_state()
        assert workflow._coerce_state(state) is state

    def test_unwraps_langgraph_nested_dict(self, workflow):
        """LangGraph often emits {'node_name': {<state fields>}} after each node.
        _coerce_state must unwrap the outer single-key dict before building the
        GmailAgentState."""
        nested = {
            "read_unread_emails": {
                "gmail_account_id": GMAIL_ACCOUNT_ID,
                "slack_user_id": SLACK_USER_ID,
                "workflow_run_id": WORKFLOW_RUN_ID,
            }
        }
        result = workflow._coerce_state(nested)

        assert isinstance(result, GmailAgentState)
        assert result.gmail_account_id == GMAIL_ACCOUNT_ID
        assert result.slack_user_id == SLACK_USER_ID
        assert result.workflow_run_id == WORKFLOW_RUN_ID

    def test_accepts_flat_state_dict(self, workflow):
        """If LangGraph ever emits a flat dict directly (no node-name wrapper),
        extract_langgraph_state returns it unchanged and we still build a valid
        GmailAgentState."""
        flat = {
            "gmail_account_id": GMAIL_ACCOUNT_ID,
            "slack_user_id": SLACK_USER_ID,
            "workflow_run_id": WORKFLOW_RUN_ID,
            "current_draft_index": 3,
        }
        result = workflow._coerce_state(flat)

        assert isinstance(result, GmailAgentState)
        assert result.current_draft_index == 3

    def test_raises_typeerror_on_unsupported_type(self, workflow):
        """Anything that isn't a GmailAgentState or a dict is a real bug; fail
        loudly rather than silently coercing."""
        with pytest.raises(TypeError, match="Unexpected state type from LangGraph stream"):
            workflow._coerce_state("not a state")

        with pytest.raises(TypeError):
            workflow._coerce_state(42)


class TestApplyResumeAction:
    """_apply_resume_action is the single source of truth for approve/reject/save
    state transitions. Today all three advance the draft index; tomorrow they
    may diverge."""

    @pytest.mark.parametrize(
        "action",
        [ResumeAction.APPROVE_DRAFT, ResumeAction.REJECT_DRAFT, ResumeAction.SAVE_DRAFT],
    )
    def test_all_actions_clear_awaiting_approval_and_advance_index(self, workflow, action):
        state = _make_state(awaiting_approval=True, current_draft_index=2)
        result = workflow._apply_resume_action(state, action)

        assert result.awaiting_approval is False
        assert result.current_draft_index == 3

    def test_returns_same_state_object(self, workflow):
        """Helper mutates and returns the same state; callers rely on this."""
        state = _make_state(awaiting_approval=True)
        result = workflow._apply_resume_action(state, ResumeAction.APPROVE_DRAFT)
        assert result is state

    def test_raises_value_error_on_unknown_action(self, workflow):
        """Defensive branch: protects against future ResumeAction members being
        added without updating this dispatch."""
        state = _make_state(awaiting_approval=True)
        with pytest.raises(ValueError, match="Unknown ResumeAction"):
            workflow._apply_resume_action(state, object())


class TestStart:
    """start() builds an initial state, streams, persists, and returns a typed
    result."""

    def test_returns_paused_result_when_stream_emits_awaiting_approval(self, workflow, mocker):
        save = mocker.patch("src.workflows.workflow.save_state_to_store")
        workflow.workflow.stream.return_value = [
            _make_state(awaiting_approval=True),
        ]

        result = workflow.start(GMAIL_ACCOUNT_ID, SLACK_USER_ID)

        assert isinstance(result, WorkflowRunResult)
        assert result.status is WorkflowResultStatus.PAUSED
        assert result.awaiting_approval is True
        assert result.workflow_run_id is not None
        save.assert_called_once()
        saved_state = save.call_args.args[0]
        assert saved_state.awaiting_approval is True

    def test_returns_completed_result_when_stream_exhausts(self, workflow, mocker):
        save = mocker.patch("src.workflows.workflow.save_state_to_store")
        workflow.workflow.stream.return_value = [
            _make_state(awaiting_approval=False, workflow_complete=True),
        ]

        result = workflow.start(GMAIL_ACCOUNT_ID, SLACK_USER_ID)

        assert result.status is WorkflowResultStatus.COMPLETED
        assert result.workflow_complete is True
        assert result.awaiting_approval is False
        save.assert_called_once()

    def test_stops_streaming_at_first_pause(self, workflow, mocker):
        """If the stream emits more states after one with awaiting_approval=True,
        we must NOT keep consuming. The pause is the stop point."""
        mocker.patch("src.workflows.workflow.save_state_to_store")
        paused = _make_state(awaiting_approval=True)
        post_pause = _make_state(workflow_complete=True)
        workflow.workflow.stream.return_value = iter([paused, post_pause])

        result = workflow.start(GMAIL_ACCOUNT_ID, SLACK_USER_ID)

        assert result.status is WorkflowResultStatus.PAUSED
        assert result.workflow_complete is False

    def test_mints_unique_workflow_run_id_per_call(self, workflow, mocker):
        """Each start() must mint a fresh UUID for the initial state. We assert
        on the workflow_run_id of the initial state passed to workflow.stream(...)
        rather than on the result, because the result reflects whatever the
        (mocked) stream emitted, not what start() minted."""
        mocker.patch("src.workflows.workflow.save_state_to_store")
        workflow.workflow.stream.return_value = [
            _make_state(awaiting_approval=True),
        ]

        workflow.start(GMAIL_ACCOUNT_ID, SLACK_USER_ID)
        first_run_id = workflow.workflow.stream.call_args.args[0].workflow_run_id

        workflow.start(GMAIL_ACCOUNT_ID, SLACK_USER_ID)
        second_run_id = workflow.workflow.stream.call_args.args[0].workflow_run_id

        assert first_run_id is not None
        assert second_run_id is not None
        assert first_run_id != second_run_id

    def test_initial_state_carries_caller_identities(self, workflow, mocker):
        """The first state passed to workflow.stream(...) must contain the
        gmail_account_id and slack_user_id from the caller."""
        mocker.patch("src.workflows.workflow.save_state_to_store")
        workflow.workflow.stream.return_value = [
            _make_state(awaiting_approval=True),
        ]

        workflow.start(GMAIL_ACCOUNT_ID, SLACK_USER_ID)

        initial_state = workflow.workflow.stream.call_args.args[0]
        assert initial_state.gmail_account_id == GMAIL_ACCOUNT_ID
        assert initial_state.slack_user_id == SLACK_USER_ID
        assert initial_state.workflow_run_id is not None

    def test_resets_seen_message_ids(self, workflow, mocker):
        """A fresh run must clear the per-run deduplication tracker."""
        mocker.patch("src.workflows.workflow.save_state_to_store")
        workflow._seen_message_ids = {"prior-msg-1", "prior-msg-2"}
        workflow.workflow.stream.return_value = [
            _make_state(workflow_complete=True),
        ]

        workflow.start(GMAIL_ACCOUNT_ID, SLACK_USER_ID)

        assert workflow._seen_message_ids == set()


class TestResume:
    """resume() loads saved state, enforces ownership, applies the user action,
    streams to the next pause/completion, persists, and returns a typed
    result."""

    def test_returns_not_found_when_no_saved_state(self, workflow, mocker):
        mocker.patch("src.workflows.workflow.load_state_from_store", return_value=None)
        save = mocker.patch("src.workflows.workflow.save_state_to_store")

        result = workflow.resume(WORKFLOW_RUN_ID, GMAIL_ACCOUNT_ID, ResumeAction.APPROVE_DRAFT)

        assert result.status is WorkflowResultStatus.NOT_FOUND
        assert result.workflow_run_id == WORKFLOW_RUN_ID
        assert "No saved workflow state" in (result.error_message or "")
        workflow.workflow.stream.assert_not_called()
        save.assert_not_called()

    def test_returns_forbidden_when_caller_does_not_own_run(self, workflow, mocker):
        saved = _make_state(gmail_account_id=OTHER_GMAIL_ACCOUNT_ID, awaiting_approval=True)
        mocker.patch("src.workflows.workflow.load_state_from_store", return_value=saved)
        save = mocker.patch("src.workflows.workflow.save_state_to_store")

        result = workflow.resume(WORKFLOW_RUN_ID, GMAIL_ACCOUNT_ID, ResumeAction.APPROVE_DRAFT)

        assert result.status is WorkflowResultStatus.FORBIDDEN
        assert "different gmail_account_id" in (result.error_message or "")
        workflow.workflow.stream.assert_not_called()
        save.assert_not_called()

    @pytest.mark.parametrize(
        "action",
        [ResumeAction.APPROVE_DRAFT, ResumeAction.REJECT_DRAFT, ResumeAction.SAVE_DRAFT],
    )
    def test_each_action_advances_state_then_streams(self, workflow, mocker, action):
        """For all three actions, resume() must apply the transition AND then
        stream the workflow forward, AND persist the final state. This is the
        regression test for the existing Slack bridge bug where the action type
        was ignored."""
        saved = _make_state(awaiting_approval=True, current_draft_index=1)
        mocker.patch("src.workflows.workflow.load_state_from_store", return_value=saved)
        save = mocker.patch("src.workflows.workflow.save_state_to_store")
        workflow.workflow.stream.return_value = [
            _make_state(awaiting_approval=False, workflow_complete=True, current_draft_index=2),
        ]

        result = workflow.resume(WORKFLOW_RUN_ID, GMAIL_ACCOUNT_ID, action)

        assert result.status is WorkflowResultStatus.COMPLETED
        workflow.workflow.stream.assert_called_once()
        streamed_state = workflow.workflow.stream.call_args.args[0]
        assert streamed_state.awaiting_approval is False
        assert streamed_state.current_draft_index == 2
        save.assert_called_once()

    def test_returns_paused_when_next_pause_hit(self, workflow, mocker):
        """If the streamed workflow pauses again for the next draft's approval,
        resume() returns PAUSED so the user can be re-prompted."""
        saved = _make_state(awaiting_approval=True, current_draft_index=0)
        mocker.patch("src.workflows.workflow.load_state_from_store", return_value=saved)
        mocker.patch("src.workflows.workflow.save_state_to_store")
        workflow.workflow.stream.return_value = [
            _make_state(awaiting_approval=True, current_draft_index=1),
        ]

        result = workflow.resume(WORKFLOW_RUN_ID, GMAIL_ACCOUNT_ID, ResumeAction.APPROVE_DRAFT)

        assert result.status is WorkflowResultStatus.PAUSED
        assert result.awaiting_approval is True

    def test_does_not_call_load_state_more_than_once(self, workflow, mocker):
        """Sanity check: a single resume() call should hit the state store once
        for load, once for save."""
        saved = _make_state(awaiting_approval=True)
        load = mocker.patch("src.workflows.workflow.load_state_from_store", return_value=saved)
        mocker.patch("src.workflows.workflow.save_state_to_store")
        workflow.workflow.stream.return_value = [
            _make_state(workflow_complete=True),
        ]

        workflow.resume(WORKFLOW_RUN_ID, GMAIL_ACCOUNT_ID, ResumeAction.APPROVE_DRAFT)

        assert load.call_count == 1
        load.assert_called_with(WORKFLOW_RUN_ID)
