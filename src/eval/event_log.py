import logging
import threading
from pathlib import Path
from typing import Union

from src.eval.event_schema import HumanDecisionRecorded, MetricEvent
from src.eval.human_decision import HumanDecision

logger = logging.getLogger(__name__)

DEFAULT_EVENT_LOG_PATH = "metrics/events.jsonl"


class EventLog:
    """Append-only JSONL sink for metric events.

    Serializes each event as a single JSON object and appends it as one line to
    a file. Writes are serialized with a lock so events produced by concurrent
    handlers are not interleaved, and write failures are logged rather than
    raised so recording never interrupts the caller.

    Attributes:
        path (Path): Filesystem path of the JSONL file events are appended to.
    """

    def __init__(self, path: Union[str, Path] = DEFAULT_EVENT_LOG_PATH) -> None:
        """Create an EventLog that appends events to the given file.

        Args:
            path (Union[str, Path]): Path to the JSONL file events are written
                to. The parent directory is created on the first write if it
                does not exist. Defaults to "metrics/events.jsonl".
        """
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, event: MetricEvent) -> None:
        """Append a single event to the log as one JSON line.

        Serialization and file writing are performed under a lock. Logs the
        inbound event before writing and the serialized line with its
        destination path after a successful write. Any OSError raised while
        writing is logged and suppressed so a failed write does not propagate to
        the caller.

        Args:
            event (MetricEvent): The event to serialize and append.
        """
        line = event.model_dump_json()
        logger.info("EventLog.record received event=%r", event)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            logger.info("EventLog.record wrote to %s: %s", self.path, line)
        except OSError:
            logger.exception("Failed to write metric event to %s", self.path)

    def record_human_decision(self, decision: HumanDecision) -> None:
        """Append a HumanDecisionRecorded event built from a decision.

        Logs the inbound decision before converting it to a
        HumanDecisionRecorded event and appending it via ``record``.

        Args:
            decision (HumanDecision): The user's decision on a draft, converted
                to a HumanDecisionRecorded event before being appended.
        """
        logger.info("EventLog.record_human_decision received decision=%r", decision)
        self.record(HumanDecisionRecorded.from_decision(decision))
