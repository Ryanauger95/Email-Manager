from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for CloudWatch."""

    def __init__(self, request_id: Optional[str] = None):
        super().__init__()
        self._request_id = request_id

    def set_request_id(self, request_id: str) -> None:
        self._request_id = request_id

    def set_state(self, state: str) -> None:
        self._state = state

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        if self._request_id:
            log_entry["request_id"] = self._request_id

        if hasattr(self, "_state"):
            log_entry["state"] = self._state

        if hasattr(record, "state"):
            log_entry["state"] = record.state

        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms

        if record.exc_info and record.exc_info[1]:
            log_entry["error_type"] = type(record.exc_info[1]).__name__
            log_entry["error_message"] = str(record.exc_info[1])
            log_entry["traceback"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable formatter for local development."""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


_json_formatter: Optional[JsonFormatter] = None


def setup_logging(
    level: str = "INFO",
    log_format: str = "json",
    request_id: Optional[str] = None,
) -> JsonFormatter | TextFormatter:
    """Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: "json" for Lambda/CloudWatch, "text" for local dev.
        request_id: AWS Lambda request ID for correlation.

    Returns:
        The formatter instance (useful for updating state later).
    """
    global _json_formatter

    log_level = os.environ.get("LOG_LEVEL", level).upper()
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove existing handlers to avoid duplicates on warm Lambda starts
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)

    if log_format == "json":
        formatter = JsonFormatter(request_id=request_id)
        _json_formatter = formatter
    else:
        formatter = TextFormatter()

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    logging.getLogger("google.auth").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return formatter


def get_json_formatter() -> Optional[JsonFormatter]:
    return _json_formatter
