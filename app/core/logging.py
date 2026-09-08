"""Structured runtime logging without secret leakage."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from .models import EventRecord


class JsonEventFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

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
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int = logging.INFO) -> logging.Logger:
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
    """Log a structured event. Secret values must never be passed in metadata."""
    logger.log(level, event.short_message, extra={"event": event})
