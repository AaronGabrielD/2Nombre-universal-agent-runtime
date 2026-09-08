"""Thread-safe in-memory session repository for the first runtime milestone."""
from __future__ import annotations

from threading import RLock
from typing import Protocol

from app.core.exceptions import RuntimeErrorBase

from .models import SessionRecord


class SessionNotFoundError(RuntimeErrorBase):
    """Raised when a run_id does not exist in the repository."""


class SessionRepository(Protocol):
    def create(self, record: SessionRecord) -> SessionRecord: ...
    def get(self, run_id: str) -> SessionRecord: ...
    def delete(self, run_id: str) -> None: ...
    def contains(self, run_id: str) -> bool: ...


class InMemorySessionRepository:
    """Process-local repository; persistence is intentionally deferred."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = RLock()

    def create(self, record: SessionRecord) -> SessionRecord:
        run_id = record.context.run_id
        if not run_id.strip():
            raise ValueError("run_id cannot be empty")
        with self._lock:
            if run_id in self._sessions:
                raise ValueError(f"run_id already exists: {run_id}")
            self._sessions[run_id] = record
            return record

    def get(self, run_id: str) -> SessionRecord:
        with self._lock:
            try:
                return self._sessions[run_id]
            except KeyError as exc:
                raise SessionNotFoundError(f"Unknown run_id: {run_id}") from exc

    def delete(self, run_id: str) -> None:
        with self._lock:
            if run_id not in self._sessions:
                raise SessionNotFoundError(f"Unknown run_id: {run_id}")
            del self._sessions[run_id]

    def contains(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._sessions
