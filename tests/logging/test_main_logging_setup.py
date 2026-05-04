import importlib
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from unittest.mock import patch

from src.utils.json_formatter import JsonFormatter


def test_main_logging_setup(tmp_path, monkeypatch):
    """
    Test logging setup in main.py
    """
    log_path = tmp_path / "app.log"
    monkeypatch.setenv("LOG_FILE", str(log_path))

    with (
        patch("slack_bolt.App"),
        patch("src.workflows.factory.get_workflow"),
        patch("src.utils.load_env.load_dotenv_helper"),
    ):
        import main

        importlib.reload(main)

    root = logging.getLogger()

    assert root.level == logging.INFO

    handlers = [h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)]
    assert len(handlers) >= 1

    handler = handlers[0]

    assert handler.baseFilename == str(log_path)
    assert handler.when == "MIDNIGHT"
    assert handler.backupCount == 30

    fmt = handler.formatter
    assert fmt is not None
    assert isinstance(fmt, JsonFormatter)

    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="hello from test",
        args=(),
        exc_info=None,
    )
    output = json.loads(fmt.format(record))
    assert output["level"] == "INFO"
    assert output["logger"] == "test.logger"
    assert output["message"] == "hello from test"
    assert "timestamp" in output
