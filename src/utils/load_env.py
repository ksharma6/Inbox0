import os
from pathlib import Path

from dotenv import load_dotenv

REQUIRED_VARS = [
    "OPENROUTER_API_KEY",
    "LANGSMITH_API_KEY",
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "TOKENS_PATH",
]


def load_dotenv_helper():
    """Load the .env file from the current working directory or the project root directory."""

    if load_dotenv():
        print("Successfully loaded .env (default search).")
    else:
        project_root_env_alt = Path.cwd() / ".env"
        if project_root_env_alt.exists():
            load_dotenv(dotenv_path=project_root_env_alt)
            print(f"Loaded .env from CWD: {project_root_env_alt}")
        else:
            print("Warning: .env file not found via default search or in CWD.")

    missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Please check your .env file against .env.example."
        )
