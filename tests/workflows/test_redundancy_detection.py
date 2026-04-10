import logging
from unittest.mock import patch

import pytest
from src.agent.agent import Agent
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
from src.models.gmail import EmailMessage
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler
from src.workflows.workflow import EmailProcessingWorkflow


def make_email(msg_id: str, thread_id: str) -> EmailMessage:
    return EmailMessage(
        id=msg_id,
        subject="Test subject",
        from_email="sender@example.com",
        to_email="me@example.com",
        date="2026-04-05",
        body="Test body content.",
        thread_id=thread_id,
    )


@pytest.fixture
def workflow(mocker):
    """EmailProcessingWorkflow with all external dependencies mocked out."""
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
    return wf


class TestDetectThreadDuplication:
    def test_no_duplicates_emits_no_warning(self, workflow, caplog):
        emails = [
            make_email("msg_1", "thread_a"),
            make_email("msg_2", "thread_b"),
            make_email("msg_3", "thread_c"),
        ]
        with caplog.at_level(logging.WARNING, logger="src.workflows.workflow"):
            workflow._detect_thread_duplication(emails, step="test_step")

        assert "redundant_context" not in caplog.text

    def test_single_thread_duplicated_emits_warning(self, workflow, caplog):
        emails = [
            make_email("msg_1", "thread_a"),
            make_email("msg_2", "thread_a"),
            make_email("msg_3", "thread_b"),
        ]
        with caplog.at_level(logging.WARNING, logger="src.workflows.workflow"):
            workflow._detect_thread_duplication(emails, step="generate_email_summary")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert warnings[0].event == "redundant_context"
        assert warnings[0].thread_id == "thread_a"
        assert warnings[0].message_count_in_thread == 2
        assert warnings[0].step == "generate_email_summary"

    def test_multiple_threads_duplicated_emits_one_warning_each(self, workflow, caplog):
        emails = [
            make_email("msg_1", "thread_a"),
            make_email("msg_2", "thread_a"),
            make_email("msg_3", "thread_b"),
            make_email("msg_4", "thread_b"),
            make_email("msg_5", "thread_b"),
        ]
        with caplog.at_level(logging.WARNING, logger="src.workflows.workflow"):
            workflow._detect_thread_duplication(emails, step="process_emails_for_drafts")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2

        warned_threads = {r.thread_id: r.message_count_in_thread for r in warnings}
        assert warned_threads["thread_a"] == 2
        assert warned_threads["thread_b"] == 3

    def test_empty_email_list_emits_no_warning(self, workflow, caplog):
        with caplog.at_level(logging.WARNING, logger="src.workflows.workflow"):
            workflow._detect_thread_duplication([], step="test_step")

        assert not caplog.records


class TestDetectCrossStepDuplicates:
    def test_first_call_no_prior_state_emits_no_warning(self, workflow, caplog):
        emails = [make_email("msg_1", "thread_a"), make_email("msg_2", "thread_b")]

        with caplog.at_level(logging.WARNING, logger="src.workflows.workflow"):
            workflow._detect_cross_step_duplicates(emails, step="generate_email_summary")

        assert "duplicate_message_ids" not in caplog.text

    def test_first_call_accumulates_ids(self, workflow):
        emails = [make_email("msg_1", "thread_a"), make_email("msg_2", "thread_b")]
        workflow._detect_cross_step_duplicates(emails, step="generate_email_summary")

        assert workflow._seen_message_ids == {"msg_1", "msg_2"}

    def test_second_call_all_new_ids_emits_no_warning(self, workflow, caplog):
        workflow._seen_message_ids = {"msg_1", "msg_2"}
        emails = [make_email("msg_3", "thread_c"), make_email("msg_4", "thread_d")]

        with caplog.at_level(logging.WARNING, logger="src.workflows.workflow"):
            workflow._detect_cross_step_duplicates(emails, step="process_emails_for_drafts")

        assert "duplicate_message_ids" not in caplog.text
        assert workflow._seen_message_ids == {"msg_1", "msg_2", "msg_3", "msg_4"}

    def test_second_call_with_overlap_emits_warning(self, workflow, caplog):
        workflow._seen_message_ids = {"msg_1", "msg_2"}
        emails = [make_email("msg_2", "thread_a"), make_email("msg_3", "thread_b")]

        with caplog.at_level(logging.WARNING, logger="src.workflows.workflow"):
            workflow._detect_cross_step_duplicates(emails, step="process_emails_for_drafts")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert warnings[0].event == "duplicate_message_ids"
        assert "msg_2" in warnings[0].reused_ids
        assert warnings[0].step == "process_emails_for_drafts"

    def test_overlap_warning_contains_only_overlapping_ids(self, workflow, caplog):
        workflow._seen_message_ids = {"msg_1", "msg_2"}
        emails = [
            make_email("msg_1", "thread_a"),
            make_email("msg_2", "thread_b"),
            make_email("msg_3", "thread_c"),
        ]

        with caplog.at_level(logging.WARNING, logger="src.workflows.workflow"):
            workflow._detect_cross_step_duplicates(emails, step="process_emails_for_drafts")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert set(warnings[0].reused_ids) == {"msg_1", "msg_2"}
        assert "msg_3" not in warnings[0].reused_ids

    def test_run_resets_seen_ids_between_runs(self, workflow):
        """IDs from a previous run must not bleed into the next run."""
        workflow._seen_message_ids = {"msg_from_previous_run"}

        workflow.workflow.stream = lambda state, **kwargs: iter([{}])
        workflow.run(user_id="test_user")

        assert "msg_from_previous_run" not in workflow._seen_message_ids
