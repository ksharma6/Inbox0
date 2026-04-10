"""
ADR 001 — Token Growth Hypothesis

Tests that the prompt token count fed into _generate_email_summary grows linearly
with thread depth. The quoted-reply structure in DEEP_THREAD_40 means each
message re-includes all prior content, so growth is expected to be at minimum
linear which is the root cause of the demo hang.

No LLM call is made. Token counts are measured directly on the formatted
string that _format_emails_for_summary would embed in the prompt, using the
same cl100k_base encoding that Agent._estimate_prompt_tokens uses as a fallback.

Results are written to reports/adr001_token_growth.csv for review alongside
the ADR.
"""

import csv
import os
from unittest.mock import patch

import pytest
import tiktoken
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


class TestTokenGrowth:
    DEPTHS = [5, 10, 20, 40]

    def _count_tokens(self, text: str) -> int:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))

    def _measure(self, workflow, emails_by_depth: dict) -> list[dict]:
        rows = []
        for depth in self.DEPTHS:
            emails = emails_by_depth[depth]
            formatted = workflow._format_emails_for_summary(emails)
            tokens = self._count_tokens(formatted)
            rows.append({"depth": depth, "tokens": tokens, "chars": len(formatted)})
            print(f"depth={depth:>3}  tokens={tokens:>6}  chars={len(formatted):>8}")
        return rows

    def test_prompt_token_count_grows_monotonically(self, workflow, deep_thread_40):
        """Token count must strictly increase at every depth step."""
        emails_by_depth = {d: deep_thread_40[:d] for d in self.DEPTHS}
        rows = self._measure(workflow, emails_by_depth)
        token_counts = [r["tokens"] for r in rows]

        for i in range(1, len(token_counts)):
            assert token_counts[i] > token_counts[i - 1], (
                f"Token count did not grow between depth "
                f"{self.DEPTHS[i - 1]} and {self.DEPTHS[i]}: "
                f"{token_counts[i - 1]} -> {token_counts[i]}"
            )

    def test_token_growth_is_at_least_linear(self, workflow, deep_thread_40):
        """Doubling depth must at least double the token count.

        Because each reply re-quotes all prior messages, growth is expected to
        be super-linear. This test establishes the floor — confirming the
        compounding behaviour that drives the latency problem in ADR 001.
        """
        emails_by_depth = {d: deep_thread_40[:d] for d in self.DEPTHS}
        rows = self._measure(workflow, emails_by_depth)
        counts = {r["depth"]: r["tokens"] for r in rows}

        assert (
            counts[20] >= counts[10] * 2
        ), f"Expected at least 2x growth from depth 10 to 20: {counts[10]} -> {counts[20]}"
        assert (
            counts[40] >= counts[20] * 2
        ), f"Expected at least 2x growth from depth 20 to 40: {counts[20]} -> {counts[40]}"

    def test_writes_results_to_csv(self, workflow, deep_thread_40):
        """Persist token measurements to reports/ for review alongside ADR 001."""
        os.makedirs("reports", exist_ok=True)
        emails_by_depth = {d: deep_thread_40[:d] for d in self.DEPTHS}
        rows = self._measure(workflow, emails_by_depth)

        out_path = "reports/adr001_token_growth.csv"
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["depth", "tokens", "chars"])
            writer.writeheader()
            writer.writerows(rows)

        assert os.path.exists(out_path)
        with open(out_path) as f:
            written = list(csv.DictReader(f))
        assert len(written) == len(self.DEPTHS)
