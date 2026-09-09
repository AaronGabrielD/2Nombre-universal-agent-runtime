"""Session repositories used by M01.

The repository contract is intentionally provider-agnostic. SQLite support uses
only the Python standard library so the runtime can persist runs in Colab or a
small local deployment without adding a database service dependency.
"""
from __future__ import annotations

import sqlite3
from copy import deepcopy
import pickle
from threading import RLock
from typing import Protocol

from app.core.exceptions import RuntimeErrorBase

from .models import SessionRecord


class SessionNotFoundError(RuntimeErrorBase):
    """Raised when a run_id does not exist in the repository."""


class SessionRepositoryError(RuntimeErrorBase):
    """Raised when persistent session storage cannot be read or written."""


class SessionRepository(Protocol):
    def create(self, record: SessionRecord) -> SessionRecord: ...
    def get(self, run_id: str) -> SessionRecord: ...
    def save(self, record: SessionRecord) -> SessionRecord: ...
    def delete(self, run_id: str) -> None: ...
    def contains(self, run_id: str) -> bool: ...


class InMemorySessionRepository:
    """Process-local repository."""

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

    def save(self, record: SessionRecord) -> SessionRecord:
        run_id = record.context.run_id
        with self._lock:
            if run_id not in self._sessions:
                raise SessionNotFoundError(f"Unknown run_id: {run_id}")
            self._sessions[run_id] = record
            return record

    def delete(self, run_id: str) -> None:
        with self._lock:
            if run_id not in self._sessions:
                raise SessionNotFoundError(f"Unknown run_id: {run_id}")
            del self._sessions[run_id]

    def contains(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._sessions


class SQLiteSessionRepository:
    """Persistent M01 repository backed by one SQLite database file.

    Stored session records are serialized with pickle. The database must be
    treated as trusted application storage; do not unpickle attacker-controlled
    database files.
    """

    def __init__(self, database_path: str) -> None:
        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("database_path cannot be empty")
        self._database_path = database_path
        self._lock = RLock()
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        run_id TEXT PRIMARY KEY,
                        payload BLOB NOT NULL
                    )
                    """
                )
        except sqlite3.Error as exc:
            raise SessionRepositoryError(f"failed to initialize SQLite repository: {exc}") from exc

    def create(self, record: SessionRecord) -> SessionRecord:
        run_id = record.context.run_id
        if not run_id.strip():
            raise ValueError("run_id cannot be empty")
        payload = sqlite3.Binary(pickle.dumps(record, protocol=pickle.HIGHEST_PROTOCOL))
        with self._lock:
            try:
                with sqlite3.connect(self._database_path) as connection:
                    connection.execute(
                        "INSERT INTO sessions(run_id, payload) VALUES (?, ?)",
                        (run_id, payload),
                    )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"run_id already exists: {run_id}") from exc
            except sqlite3.Error as exc:
                raise SessionRepositoryError(f"failed to create session {run_id}: {exc}") from exc
        return record

    def get(self, run_id: str) -> SessionRecord:
        with self._lock:
            try:
                with sqlite3.connect(self._database_path) as connection:
                    row = connection.execute(
                        "SELECT payload FROM sessions WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()
            except sqlite3.Error as exc:
                raise SessionRepositoryError(f"failed to read session {run_id}: {exc}") from exc
        if row is None:
            raise SessionNotFoundError(f"Unknown run_id: {run_id}")
        try:
            record = pickle.loads(row[0])
        except (pickle.PickleError, EOFError, AttributeError, ValueError, TypeError) as exc:
            raise SessionRepositoryError(f"stored session {run_id} is corrupt") from exc
        if not isinstance(record, SessionRecord):
            raise SessionRepositoryError(f"stored session {run_id} has an invalid record type")
        return record

    def save(self, record: SessionRecord) -> SessionRecord:
        run_id = record.context.run_id
        if not run_id.strip():
            raise ValueError("run_id cannot be empty")
        payload = sqlite3.Binary(pickle.dumps(record, protocol=pickle.HIGHEST_PROTOCOL))
        with self._lock:
            try:
                with sqlite3.connect(self._database_path) as connection:
                    cursor = connection.execute(
                        "UPDATE sessions SET payload = ? WHERE run_id = ?",
                        (payload, run_id),
                    )
                    if cursor.rowcount != 1:
                        raise SessionNotFoundError(f"Unknown run_id: {run_id}")
            except SessionNotFoundError:
                raise
            except sqlite3.Error as exc:
                raise SessionRepositoryError(f"failed to save session {run_id}: {exc}") from exc
        return record

    def delete(self, run_id: str) -> None:
        with self._lock:
            try:
                with sqlite3.connect(self._database_path) as connection:
                    cursor = connection.execute("DELETE FROM sessions WHERE run_id = ?", (run_id,))
                    if cursor.rowcount != 1:
                        raise SessionNotFoundError(f"Unknown run_id: {run_id}")
            except SessionNotFoundError:
                raise
            except sqlite3.Error as exc:
                raise SessionRepositoryError(f"failed to delete session {run_id}: {exc}") from exc

    def contains(self, run_id: str) -> bool:
        with self._lock:
            try:
                with sqlite3.connect(self._database_path) as connection:
                    row = connection.execute(
                        "SELECT 1 FROM sessions WHERE run_id = ? LIMIT 1",
                        (run_id,),
                    ).fetchone()
            except sqlite3.Error as exc:
                raise SessionRepositoryError(f"failed to check session {run_id}: {exc}") from exc
        return row is not None
