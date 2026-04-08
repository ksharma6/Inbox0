import pytest

from tests.fixtures.email_datasets import DEEP_THREAD_40, EDGE_CASES, MULTI_THREAD_INBOX


@pytest.fixture
def deep_thread_40():
    """40 messages in a single thread with growing quoted-reply chains.

    Use to confirm ADR 001 hypothesis: prompt token count grows linearly with
    thread depth and to establish a latency baseline before caching.

    Example::

        def test_token_growth(workflow, mocker, deep_thread_40):
            mocker.patch.object(
                workflow.gmail_reader, "read_emails", return_value=deep_thread_40
            )
    """
    return DEEP_THREAD_40


@pytest.fixture
def multi_thread_inbox():
    """6 messages across 3 threads (2 per thread).

    Use to trigger _detect_thread_duplication warnings and test deduplication behaviour.
    """
    return MULTI_THREAD_INBOX


@pytest.fixture
def edge_cases():
    """3 messages with boundary input shapes: empty body, very long body,
    and a body containing HTML artifacts.

    Use to guard error-handling paths against malformed or extreme input.
    """
    return EDGE_CASES
