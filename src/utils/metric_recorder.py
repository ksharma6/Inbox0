"""Append-only JSONL sink for gold-metric events.

Mirrors the lightweight on-disk pattern used by `UsageTracker`: each call
serializes one Pydantic event to a single line of JSON and appends it to a
file under `.inbox0/metrics/`. The directory is created lazily on first write
so importing this module never produces a side effect.

Recording is best-effort. Any I/O or serialization failure is logged but never
raised, so a broken metrics sink can never break a real workflow run.
"""

import logging
from pathlib import Path
from typing import Optional

from src.models.metric_events import (
    DraftGeneratedEvent,
    EmailObservedEvent,
    GmailDraftSavedEvent,
    LlmStageLiteral,
    LlmUsageRecordedEvent,
    MetricEvent,
    SlackActionLiteral,
    SlackActionRecordedEvent,
    SlackDraftPresentedEvent,
    WorkflowCompletedEvent,
    WorkflowStartedEvent,
)

logger = logging.getLogger(__name__)

DEFAULT_METRICS_PATH = Path(".inbox0/metrics/events.jsonl")


class MetricRecorder:
    """Writes typed metric events as one JSON object per line.

    The default path lives under an ignored `.inbox0/` directory so eval data
    accumulates locally without polluting the repo. Pass a different `path`
    (typically a `tmp_path` fixture) in tests.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else DEFAULT_METRICS_PATH

    def _write(self, event: MetricEvent) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
        except Exception:
            logger.exception(
                "Failed to record metric event",
                extra={"event_type": getattr(event, "event_type", "unknown"), "path": str(self.path)},
            )

    def record_workflow_started(
        self,
        workflow_run_id: str,
        gmail_account_id: Optional[str] = None,
        slack_user_id: Optional[str] = None,
    ) -> None:
        self._write(
            WorkflowStartedEvent(
                workflow_run_id=workflow_run_id,
                gmail_account_id=gmail_account_id,
                slack_user_id=slack_user_id,
            )
        )

    def record_email_observed(
        self,
        workflow_run_id: str,
        email_id: str,
        thread_id: str,
        gmail_account_id: Optional[str] = None,
        slack_user_id: Optional[str] = None,
    ) -> None:
        self._write(
            EmailObservedEvent(
                workflow_run_id=workflow_run_id,
                gmail_account_id=gmail_account_id,
                slack_user_id=slack_user_id,
                email_id=email_id,
                thread_id=thread_id,
            )
        )

    def record_draft_generated(
        self,
        workflow_run_id: str,
        draft_id: str,
        email_id: str,
        thread_id: str,
        gmail_account_id: Optional[str] = None,
        slack_user_id: Optional[str] = None,
    ) -> None:
        self._write(
            DraftGeneratedEvent(
                workflow_run_id=workflow_run_id,
                gmail_account_id=gmail_account_id,
                slack_user_id=slack_user_id,
                draft_id=draft_id,
                email_id=email_id,
                thread_id=thread_id,
            )
        )

    def record_slack_draft_presented(
        self,
        workflow_run_id: str,
        draft_id: str,
        slack_user_id: Optional[str] = None,
        gmail_account_id: Optional[str] = None,
    ) -> None:
        self._write(
            SlackDraftPresentedEvent(
                workflow_run_id=workflow_run_id,
                gmail_account_id=gmail_account_id,
                slack_user_id=slack_user_id,
                draft_id=draft_id,
            )
        )

    def record_slack_action(
        self,
        workflow_run_id: str,
        draft_id: str,
        action: SlackActionLiteral,
        shadow_mode: bool,
        slack_user_id: Optional[str] = None,
        gmail_account_id: Optional[str] = None,
    ) -> None:
        self._write(
            SlackActionRecordedEvent(
                workflow_run_id=workflow_run_id,
                gmail_account_id=gmail_account_id,
                slack_user_id=slack_user_id,
                draft_id=draft_id,
                action=action,
                shadow_mode=shadow_mode,
            )
        )

    def record_gmail_draft_saved(
        self,
        workflow_run_id: str,
        draft_id: str,
        gmail_draft_id: Optional[str] = None,
        gmail_account_id: Optional[str] = None,
        slack_user_id: Optional[str] = None,
    ) -> None:
        self._write(
            GmailDraftSavedEvent(
                workflow_run_id=workflow_run_id,
                gmail_account_id=gmail_account_id,
                slack_user_id=slack_user_id,
                draft_id=draft_id,
                gmail_draft_id=gmail_draft_id,
            )
        )

    def record_llm_usage(
        self,
        workflow_run_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        stage: Optional[LlmStageLiteral] = None,
        gmail_account_id: Optional[str] = None,
        slack_user_id: Optional[str] = None,
    ) -> None:
        self._write(
            LlmUsageRecordedEvent(
                workflow_run_id=workflow_run_id,
                gmail_account_id=gmail_account_id,
                slack_user_id=slack_user_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                stage=stage,
            )
        )

    def record_workflow_completed(
        self,
        workflow_run_id: str,
        final_status: str,
        emails_observed: int,
        drafts_generated: int,
        gmail_account_id: Optional[str] = None,
        slack_user_id: Optional[str] = None,
    ) -> None:
        self._write(
            WorkflowCompletedEvent(
                workflow_run_id=workflow_run_id,
                gmail_account_id=gmail_account_id,
                slack_user_id=slack_user_id,
                final_status=final_status,
                emails_observed=emails_observed,
                drafts_generated=drafts_generated,
            )
        )
