import datetime
import json
import os
from typing import Optional

DEFAULT_METRICS_FILE = "usage_tracker.json"


class UsageTracker:
    """Records language-model token usage as JSON lines in a file.

    Attributes:
        file_path (str): Path to the file each usage entry is appended to.
    """

    def __init__(self, file_path: Optional[str] = None):
        """Create a UsageTracker that appends entries to a file.

        Args:
            file_path (Optional[str]): Path to the JSON-lines file usage entries
                are written to. When None, the path is read from the
                METRICS_FILE environment variable, falling back to
                "usage_tracker.json" when that is unset.
        """
        self.file_path = file_path or os.getenv("METRICS_FILE", DEFAULT_METRICS_FILE)

    def log_usage(
        self,
        model: str,
        site_url: str,
        prompt_tokens: int,
        completion_tokens: int,
        user_id: str = "unknown",
        workflow_run_id: Optional[str] = None,
        stage: Optional[str] = None,
        draft_id: Optional[str] = None,
    ) -> None:
        """Append a single token-usage entry to the file.

        Args:
            model (str): Name of the model that produced the completion.
            site_url (str): Site URL reported alongside the request.
            prompt_tokens (int): Number of tokens in the prompt.
            completion_tokens (int): Number of tokens in the completion.
            user_id (str): Identifier of the user the request was made for.
                Defaults to "unknown".
            workflow_run_id (Optional[str]): Identifier of the workflow run the
                call belongs to, used to join usage with other events. Defaults
                to None.
            stage (Optional[str]): Name of the workflow stage that made the call.
                Defaults to None.
            draft_id (Optional[str]): Identifier of the draft the call relates
                to. Defaults to None.
        """
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "user_id": user_id,
            "model": model,
            "site_url": site_url,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "workflow_run_id": workflow_run_id,
            "stage": stage,
            "draft_id": draft_id,
        }

        try:
            with open(self.file_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"Failed to log usage: {e}")
