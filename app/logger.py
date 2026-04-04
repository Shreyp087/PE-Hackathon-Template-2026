import logging
import sys
from collections import deque
from datetime import datetime, UTC

from pythonjsonlogger import jsonlogger

_STANDARD_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
}
_RECENT_LOGS = deque(maxlen=500)


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["level"] = record.levelname
        log_record["component"] = record.name
        if "timestamp" not in log_record:
            log_record["timestamp"] = self.formatTime(record, self.datefmt)


class InMemoryLogHandler(logging.Handler):
    def emit(self, record):
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOG_RECORD_FIELDS and not key.startswith("_")
        }
        _RECENT_LOGS.append(
            {
                "timestamp": datetime.fromtimestamp(
                    record.created, tz=UTC
                ).isoformat(),
                "level": record.levelname,
                "component": record.name,
                "message": record.getMessage(),
                **extras,
            }
        )


def get_recent_logs(limit=100):
    try:
        parsed_limit = max(1, min(int(limit), len(_RECENT_LOGS) or 1))
    except (TypeError, ValueError):
        parsed_limit = 100

    return list(_RECENT_LOGS)[-parsed_limit:][::-1]


def setup_logging(level="INFO"):
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(CustomJsonFormatter())
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(InMemoryLogHandler())
    root_logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)

    return root_logger


__all__ = [
    "CustomJsonFormatter",
    "InMemoryLogHandler",
    "get_recent_logs",
    "setup_logging",
]
