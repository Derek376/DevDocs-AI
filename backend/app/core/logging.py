"""JSON application logs with explicit fields; no bodies, URLs or exception text."""

import json
import logging
import sys
from datetime import UTC, datetime

logger = logging.getLogger("devdocs")
FIELDS = ("request_id", "method", "route", "status", "duration_ms", "error_type")
EVENTS = {"request_completed", "application_started", "application_stopped"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = record.getMessage()
        data = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": event if event in EVENTS else "application_event",
        }
        for field in FIELDS:
            if hasattr(record, field):
                data[field] = getattr(record, field)
        # Deliberately omit exc_info, exception messages, arbitrary extra fields.
        return json.dumps(data)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    for previous in logger.handlers[:]:
        logger.removeHandler(previous)
        previous.close()
    logger.addHandler(handler)
    logger.setLevel(level)
    # Alembic's fileConfig can disable existing loggers in embedded/test runs.
    logger.disabled = False
    logger.propagate = False
