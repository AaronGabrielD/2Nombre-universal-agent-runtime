"""Structured runtime logging with centralized secret redaction."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from typing import Any

from .models import EventRecord


_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|token|secret|password|credential|private[_-]?key|authorization|bearer)",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"
)


class JsonEventFormatter(logging.Formatter):
    """Emit one JSON object per log line with sensitive values redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if isinstance(event, EventRecord):
            payload.update(asdict(event))
            payload["timestamp"] = event.timestamp.isoformat()
        return json.dumps(_redact(payload), ensure_ascii=False, default=str)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = _BEARER_VALUE.sub("Bearer [REDACTED]", value)
        return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return value


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the process-wide runtime event logger."""
    logger = logging.getLogger("universal_agent_runtime")
    if logger.handlers:
        logger.setLevel(level)
        return logger
    handler = logging.StreamHandler()
    handler.setFormatter(JsonEventFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def log_event(
    logger: logging.Logger,
    event: EventRecord,
    *,
    level: int = logging.INFO,
) -> None:
    """Log a structured event; formatter-level redaction remains the final guard."""
    logger.log(level, event.short_message, extra={"event": event})
