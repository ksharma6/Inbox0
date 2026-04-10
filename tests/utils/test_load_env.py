from unittest.mock import patch

import pytest
from src.utils.load_env import REQUIRED_VARS, load_dotenv_helper


def test_raises_on_missing_required_vars():
    empty_env = {var: "" for var in REQUIRED_VARS}
    with patch("src.utils.load_env.load_dotenv", return_value=True), patch.dict("os.environ", empty_env, clear=True):
        with pytest.raises(RuntimeError, match="Missing required environment variables"):
            load_dotenv_helper()


def test_error_lists_langsmith_key_when_missing():
    empty_env = {var: "" for var in REQUIRED_VARS}
    with patch("src.utils.load_env.load_dotenv", return_value=True), patch.dict("os.environ", empty_env, clear=True):
        with pytest.raises(RuntimeError, match="LANGSMITH_API_KEY"):
            load_dotenv_helper()


def test_no_error_when_all_vars_present():
    full_env = {var: "dummy_value" for var in REQUIRED_VARS}
    with patch("src.utils.load_env.load_dotenv", return_value=True), patch.dict("os.environ", full_env):
        load_dotenv_helper()


def test_all_required_vars_listed_in_error():
    with patch("src.utils.load_env.load_dotenv", return_value=True), patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError) as exc_info:
            load_dotenv_helper()

    error_message = str(exc_info.value)
    for var in REQUIRED_VARS:
        assert var in error_message
