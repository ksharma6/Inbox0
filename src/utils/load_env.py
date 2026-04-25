import os
from pathlib import Path

from dotenv import load_dotenv

REQUIRED_VARS = [
    "LANGSMITH_API_KEY",
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "TOKENS_PATH",
]

REQUIRED_API_KEY_VARS = [
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
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
    missing_api_key = not any(os.getenv(var) for var in REQUIRED_API_KEY_VARS)
    if missing or missing_api_key:
        missing_display = missing.copy()
        if missing_api_key:
            missing_display.append("OPENROUTER_API_KEY or OPENAI_API_KEY")
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing_display)}\n"
            "Please check your .env file against .env.example."
        )
