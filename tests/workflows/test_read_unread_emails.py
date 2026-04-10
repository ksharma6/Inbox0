"""
Tests for EmailProcessingWorkflow._read_unread_emails using MULTI_THREAD_INBOX.

Covers:
- Deduplication of emails that appear in both read_emails and get_recent_emails_in_thread
- Result is bounded at 5 emails after thread expansion
- _detect_thread_duplication fires a warning when multiple emails share a thread_id
- Empty inbox returns empty state
"""

from collections import Counter
from unittest.mock import patch

import pytest
from src.agent.agent import Agent
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
from src.models.agent_schemas import GmailAgentState
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler
from src.workflows.workflow import EmailProcessingWorkflow


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


class TestReadUnreadEmails:
    def _make_state(self):
        return GmailAgentState(user_id="test_user", thread_id="test_thread")

    def _setup_mocks(self, workflow, multi_thread_inbox):
        """
        Simulates the two-step fetch pattern in _read_unread_emails:
        - read_emails returns one email per thread (the first message in each)
        - get_recent_emails_in_thread returns both emails for that thread

        This means the first message of each thread appears in both calls,
        exercising the deduplication logic.
        """
        per_thread = [
            multi_thread_inbox[0],
            multi_thread_inbox[2],
            multi_thread_inbox[4],
        ]

        def thread_emails(thread_id, count=2):
            return [e for e in multi_thread_inbox if e.thread_id == thread_id][:count]

        workflow.gmail_reader.read_emails.return_value = per_thread
        workflow.gmail_reader.get_recent_emails_in_thread.side_effect = thread_emails

    def test_deduplication_removes_overlap_between_fetch_and_thread_expansion(self, workflow, multi_thread_inbox):
        """
        Emails returned by read_emails that also appear in get_recent_emails_in_thread
        must not be counted twice in state.unread_emails.
        """
        self._setup_mocks(workflow, multi_thread_inbox)
        state = workflow._read_unread_emails(self._make_state())

        ids = [e.id for e in state.unread_emails]
        assert len(ids) == len(set(ids)), f"Duplicate email ids found: {ids}"

    def test_result_is_capped_at_five(self, workflow, multi_thread_inbox):
        """
        6 unique emails are collected across 3 threads after expansion.
        The [:5] slice must cap the result at 5.
        """
        self._setup_mocks(workflow, multi_thread_inbox)
        state = workflow._read_unread_emails(self._make_state())

        assert len(state.unread_emails) <= 5

    def test_thread_expansion_preserves_multiple_emails_per_thread(self, workflow, multi_thread_inbox):
        """
        get_recent_emails_in_thread returns 2 emails per thread. After deduplication
        those pairs must be preserved in state.unread_emails — not collapsed to one.
        This confirms thread expansion worked and that the downstream
        _detect_thread_duplication call in _generate_email_summary will have
        the data it needs to fire a redundant_context warning.
        """
        self._setup_mocks(workflow, multi_thread_inbox)
        state = workflow._read_unread_emails(self._make_state())

        thread_counts = Counter(e.thread_id for e in state.unread_emails)
        threads_with_multiple = [t for t, c in thread_counts.items() if c > 1]
        assert len(threads_with_multiple) >= 1, (
            f"Expected at least one thread_id to appear more than once in state.unread_emails. "
            f"Got thread counts: {dict(thread_counts)}"
        )

    def test_empty_inbox_returns_empty_state(self, workflow):
        """No emails from read_emails — state.unread_emails should be empty."""
        workflow.gmail_reader.read_emails.return_value = []
        workflow.gmail_reader.get_recent_emails_in_thread.return_value = []

        state = workflow._read_unread_emails(self._make_state())

        assert state.unread_emails == []
