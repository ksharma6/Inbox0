"""
Tests for _format_emails_for_summary and _format_emails_for_analysis
using EDGE_CASES.

Covers three boundary input shapes that are likely to expose silent failures
in the formatters before they reach the LLM:
  - Empty body
  - Very long single-message body (~12k chars)
  - HTML artifacts (raw tags and entities not stripped by the Gmail reader)
"""

from unittest.mock import patch

import pytest
from src.agent.agent import Agent
from src.gmail.gmail_reader import GmailReader
from src.gmail.gmail_writer import GmailWriter
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


class TestEdgeCaseFormatters:

    def test_formatter_handles_empty_body(self, workflow, edge_cases):
        """Empty body must produce a valid formatted string with a blank body line."""
        empty_email = next(e for e in edge_cases if e.id == "edge_empty_001")

        summary_output = workflow._format_emails_for_summary([empty_email])
        analysis_output = workflow._format_emails_for_analysis([empty_email])

        assert isinstance(summary_output, str)
        assert isinstance(analysis_output, str)
        assert empty_email.from_email in summary_output
        assert empty_email.from_email in analysis_output

    def test_formatter_handles_long_body(self, workflow, edge_cases):
        """Very long body must be included in full — nothing truncated or dropped."""
        long_email = next(e for e in edge_cases if e.id == "edge_long_001")

        summary_output = workflow._format_emails_for_summary([long_email])
        analysis_output = workflow._format_emails_for_analysis([long_email])

        assert (
            long_email.body in summary_output
        ), "Full body text must be present in summary formatter output"
        assert (
            long_email.body in analysis_output
        ), "Full body text must be present in analysis formatter output"

    def test_formatter_preserves_html_artifacts(self, workflow, edge_cases):
        """HTML tags and entities must pass through verbatim without being stripped."""
        html_email = next(e for e in edge_cases if e.id == "edge_html_001")

        summary_output = workflow._format_emails_for_summary([html_email])
        analysis_output = workflow._format_emails_for_analysis([html_email])

        for artifact in ["&amp;", "<b>", "<p>", "&copy;"]:
            assert (
                artifact in summary_output
            ), f"Expected HTML artifact '{artifact}' to be preserved in summary output"
            assert (
                artifact in analysis_output
            ), f"Expected HTML artifact '{artifact}' to be preserved in analysis output"

    def test_all_edge_cases_format_without_raising(self, workflow, edge_cases):
        """All three edge case emails must pass through both formatters without raising."""
        for email in edge_cases:
            try:
                workflow._format_emails_for_summary([email])
                workflow._format_emails_for_analysis([email])
            except Exception as exc:
                pytest.fail(f"Formatter raised on email id='{email.id}': {exc}")
