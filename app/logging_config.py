"""Structured JSON logging configuration for DealWatch."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, ClassVar


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter producing structured log entries."""

    REDACTED_KEYS: ClassVar[set[str]] = {
        "password",
        "secret",
        "token",
        "authorization",
        "api_key",
        "key",
    }

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include contextual fields if present
        for attr in [
            "request_id",
            "tracker_id",
            "subject_id",
            "offer_id",
            "source_id",
            "provider",
            "status",
            "duration_ms",
            "check_run_id",
        ]:
            if hasattr(record, attr):
                val = getattr(record, attr)
                log_entry[attr] = val

        # Sanitize any extra dict attached
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            sanitized = {}
            for k, v in record.extra_data.items():
                if any(red in k.lower() for red in self.REDACTED_KEYS):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = v
            log_entry["data"] = sanitized

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_logging(log_level: str = "INFO") -> None:
    """Configures root logger with JSON formatting."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

    # Silence overly verbose external loggers
    logging.getLogger("uvicorn.access").handlers = [handler]
    logging.getLogger("asyncio").setLevel(logging.WARNING)
