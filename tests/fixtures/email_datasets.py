"""
Static synthetic email datasets used for testing workflows.
- Each constant is a list of EmailMessage objects representing a specific email dataset.
- Each dataset is named after the workflow it is used for.

Datasets:   
- DEEP_THREAD_40: used for testing the EmailProcessingWorkflow.
    - 40 messages in a single thread with growing quoted-reply chains so that the body grows linearly with depth.
    - Matches the token-growth pattern described in ADR 001 and the demo hang.
- MULTI_THREAD_INBOX: used for testing the RedundancyDetectionWorkflow.
    - 6 messages across 3 threads (2 per thread).
    - Multiple messages per thread_id trigger _detect_thread_duplication warnings.
- EDGE_CASES: used for testing the EdgeCasesWorkflow.
    - 3 messages covering boundary and error-prone input shapes: 
        - Empty body
        - Very long single-message body (~3 000 words, no quoted replies)
        - HTML artifact body — residual tags/entities not fully stripped
"""

from datetime import datetime, timedelta

from src.models.gmail import EmailMessage

# DEEP_THREAD_40
_DEEP_THREAD_PARTICIPANTS = [
    ("alice@example.com", "bob@example.com"),
    ("bob@example.com", "alice@example.com"),
]

_DEEP_THREAD_SEED_BODY = (
    "Hi Bob, I wanted to follow up on the Q1 planning document. "
    "Could you review the attached outline and let me know if the scope looks right? "
    "I'd like to get alignment before the Friday deadline."
)

_deep_start = datetime(2026, 1, 1, 9, 0)
_deep_interval_hours = [
    2,
    4,
    1,
    8,
    3,
    5,
    2,
    10,
    1,
    6,
    3,
    2,
    7,
    4,
    1,
    9,
    2,
    5,
    3,
    8,
    1,
    4,
    6,
    2,
    3,
    7,
    1,
    5,
    2,
    4,
    9,
    3,
    2,
    6,
    1,
    4,
    8,
    2,
    3,
    5,
]


def _build_deep_thread() -> list[EmailMessage]:
    messages: list[EmailMessage] = []
    current_body = _DEEP_THREAD_SEED_BODY
    current_dt = _deep_start

    for i in range(40):
        msg_num = i + 1
        sender, recipient = _DEEP_THREAD_PARTICIPANTS[i % 2]
        msg_id = f"deep_{msg_num:03d}"
        date_str = current_dt.strftime("%Y-%m-%d %H:%M")

        if i == 0:
            body = current_body
        else:
            prev = messages[i - 1]
            quote = "\n".join(f"> {line}" for line in prev.body.splitlines())
            reply_text = (
                f"Thanks for the update. See my comments below.\n\n"
                f"On {prev.date}, {prev.from_email} wrote:\n{quote}"
            )
            body = reply_text
            current_body = body

        messages.append(
            EmailMessage(
                id=msg_id,
                subject="Re: Q1 Planning Document" if i > 0 else "Q1 Planning Document",
                from_email=sender,
                to_email=recipient,
                date=date_str,
                body=body,
                thread_id="thread_deep_001",
            )
        )
        current_dt += timedelta(hours=_deep_interval_hours[i])

    return messages


DEEP_THREAD_40: list[EmailMessage] = _build_deep_thread()

# MULTI_THREAD_INBOX

MULTI_THREAD_INBOX: list[EmailMessage] = [
    EmailMessage(
        id="multi_a_001",
        subject="Project Kickoff — Agenda",
        from_email="carol@example.com",
        to_email="me@example.com",
        date="2026-03-10 08:00",
        body="Hi, please find the agenda for tomorrow's project kickoff attached.",
        thread_id="thread_multi_a",
    ),
    EmailMessage(
        id="multi_a_002",
        subject="Re: Project Kickoff — Agenda",
        from_email="me@example.com",
        to_email="carol@example.com",
        date="2026-03-10 09:15",
        body=(
            "Got it, thanks! I'll review before the meeting.\n\n"
            "On 2026-03-10 08:00, carol@example.com wrote:\n"
            "> Hi, please find the agenda for tomorrow's project kickoff attached."
        ),
        thread_id="thread_multi_a",
    ),
    EmailMessage(
        id="multi_b_001",
        subject="Budget Approval Request",
        from_email="finance@example.com",
        to_email="me@example.com",
        date="2026-03-11 10:00",
        body="Please review and approve the Q2 budget request at your earliest convenience.",
        thread_id="thread_multi_b",
    ),
    EmailMessage(
        id="multi_b_002",
        subject="Re: Budget Approval Request",
        from_email="me@example.com",
        to_email="finance@example.com",
        date="2026-03-11 11:30",
        body=(
            "Approved. Sending confirmation shortly.\n\n"
            "On 2026-03-11 10:00, finance@example.com wrote:\n"
            "> Please review and approve the Q2 budget request at your earliest convenience."
        ),
        thread_id="thread_multi_b",
    ),
    EmailMessage(
        id="multi_c_001",
        subject="Team Offsite — Save the Date",
        from_email="hr@example.com",
        to_email="me@example.com",
        date="2026-03-12 14:00",
        body="Save the date: team offsite is scheduled for April 25–26. Details to follow.",
        thread_id="thread_multi_c",
    ),
    EmailMessage(
        id="multi_c_002",
        subject="Re: Team Offsite — Save the Date",
        from_email="me@example.com",
        to_email="hr@example.com",
        date="2026-03-12 15:45",
        body=(
            "Marked on my calendar, looking forward to it!\n\n"
            "On 2026-03-12 14:00, hr@example.com wrote:\n"
            "> Save the date: team offsite is scheduled for April 25–26. Details to follow."
        ),
        thread_id="thread_multi_c",
    ),
]


# EDGE_CASES
_LONG_BODY_PARAGRAPH = (
    "The quarterly review process requires careful consideration of all relevant metrics, "
    "including but not limited to revenue growth, customer acquisition cost, churn rate, "
    "net promoter score, and operational efficiency ratios. Each department head is expected "
    "to submit a detailed breakdown of their team's contributions to these metrics, along with "
    "a forward-looking projection for the next quarter based on current pipeline data. "
)

_LONG_BODY = _LONG_BODY_PARAGRAPH * 30

EDGE_CASES: list[EmailMessage] = [
    EmailMessage(
        id="edge_empty_001",
        subject="(No Subject)",
        from_email="noreply@example.com",
        to_email="me@example.com",
        date="2026-03-20 07:00",
        body="",
        thread_id="thread_edge_empty",
    ),
    EmailMessage(
        id="edge_long_001",
        subject="Annual Performance Review — Full Summary",
        from_email="hr@example.com",
        to_email="me@example.com",
        date="2026-03-20 08:30",
        body=_LONG_BODY,
        thread_id="thread_edge_long",
    ),
    EmailMessage(
        id="edge_html_001",
        subject="Welcome to the Platform",
        from_email="onboarding@platform.com",
        to_email="me@example.com",
        date="2026-03-20 09:00",
        body=(
            "Hello &amp; welcome! <b>Click here</b> to get started.\n"
            "<p>Your account has been created. Visit <a href='https://example.com'>example.com</a> "
            "to complete setup.</p>\n"
            "<ul><li>Step 1: Verify email</li><li>Step 2: Set password</li></ul>\n"
            "&copy; 2026 Platform Inc. &nbsp; All rights reserved."
        ),
        thread_id="thread_edge_html",
    ),
]
