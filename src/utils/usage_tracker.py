import datetime
import json
import os


class UsageTracker:
    """
    Tracks usage of the application and stores the data in a JSON file.
    """

    def __init__(self, file_path: str = "usage_tracker.json"):
        self.file_path = file_path

    def log_usage(
        self,
        model: str,
        site_url: str,
        prompt_tokens: int,
        completion_tokens: int,
        user_id: str = "unknown",
    ):
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "user_id": os.getenv("USER_ID"),
            "model": model,
            "site_url": site_url,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

        # Append to log file
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"Failed to log usage: {e}")
