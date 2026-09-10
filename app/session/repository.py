"""Session repositories used by M01.

The repository contract is intentionally provider-agnostic. SQLite support uses
only the Python standard library so the runtime can persist runs in Colab or a
small local deployment without adding a database service dependency.
"""
from __future__ import annotations

import pickle
import sqlite3
from copy import deepcopy
from threading import RLock
from typing import Protocol

from app.core.contracts import ArtifactRef, ExecutionResult, FinalResult, HumanDecision
from app.core.exceptions import ContractValidationError, RuntimeErrorBase

from .models import SessionMessage, SessionRecord, WorkerOutput


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
    def list(self) -> tuple[SessionRecord, ...]: ...


def validate_session_record_integrity(record: SessionRecord) -> SessionRecord:
    """Validate persisted session structure before exposing it to the runtime."""
    if not isinstance(record, SessionRecord):
        raise SessionRepositoryError("stored session has an invalid record type")

    run_id = record.context.run_id
    if not isinstance(run_id, str) or not run_id.strip():
        raise SessionRepositoryError("stored session has an invalid run_id")

    if not isinstance(record.messages, list):
        raise SessionRepositoryError(f"stored session {run_id} has invalid messages")
    for message in record.messages:
        if not isinstance(message, SessionMessage):
            raise SessionRepositoryError(f"stored session {run_id} has an invalid message record")
        if message.run_id != run_id:
            raise SessionRepositoryError(f"stored session {run_id} contains a cross-run message")
        if not isinstance(message.role, str) or not message.role.strip():
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid message role")
        if not isinstance(message.content, str) or not message.content.strip():
            raise SessionRepositoryError(f"stored session {run_id} contains invalid message content")
        if not isinstance(message.timestamp, str) or not message.timestamp.strip():
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid message timestamp")
        if not isinstance(message.metadata, dict):
            raise SessionRepositoryError(f"stored session {run_id} contains invalid message metadata")

    if not isinstance(record.artifacts, list):
        raise SessionRepositoryError(f"stored session {run_id} has invalid artifacts")
    for artifact in record.artifacts:
        if not isinstance(artifact, ArtifactRef):
            raise SessionRepositoryError(f"stored session {run_id} has an invalid artifact record")
        try:
            artifact.validate()
        except ContractValidationError as exc:
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid artifact") from exc

    if not isinstance(record.decisions, list):
        raise SessionRepositoryError(f"stored session {run_id} has invalid decisions")
    for decision in record.decisions:
        if not isinstance(decision, HumanDecision):
            raise SessionRepositoryError(f"stored session {run_id} has an invalid decision record")
        if decision.run_id != run_id:
            raise SessionRepositoryError(f"stored session {run_id} contains a cross-run human decision")
        try:
            decision.validate()
        except ContractValidationError as exc:
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid human decision") from exc

    if not isinstance(record.execution_results, list):
        raise SessionRepositoryError(f"stored session {run_id} has invalid execution results")
    for result in record.execution_results:
        if not isinstance(result, ExecutionResult):
            raise SessionRepositoryError(f"stored session {run_id} has an invalid execution result")
        try:
            result.validate()
        except ContractValidationError as exc:
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid execution result") from exc

    if not isinstance(record.worker_outputs, dict):
        raise SessionRepositoryError(f"stored session {run_id} has invalid worker outputs")
    for worker_id, output in record.worker_outputs.items():
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid worker identifier")
        if not isinstance(output, WorkerOutput) or output.worker_id != worker_id:
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid worker output")
        if output.run_id != run_id:
            raise SessionRepositoryError(f"stored session {run_id} contains a cross-run worker output")
        if not isinstance(output.status, str) or not output.status.strip():
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid worker output status")
        if not isinstance(output.timestamp, str) or not output.timestamp.strip():
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid worker output timestamp")

    if record.architecture_plan is not None:
        try:
            record.architecture_plan.validate()
        except ContractValidationError as exc:
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid architecture plan") from exc

    if record.final_result is not None:
        if not isinstance(record.final_result, FinalResult):
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid final result")
        if record.final_result.run_id != run_id:
            raise SessionRepositoryError(f"stored session {run_id} contains a cross-run final result")
        try:
            record.final_result.validate()
        except ContractValidationError as exc:
            raise SessionRepositoryError(f"stored session {run_id} contains an invalid final result") from exc

    return record


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

    def list(self) -> tuple[SessionRecord, ...]:
        with self._lock:
            return tuple(deepcopy(self._sessions[run_id]) for run_id in sorted(self._sessions))


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
        return self._decode(run_id, row[0])

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

    def list(self) -> tuple[SessionRecord, ...]:
        with self._lock:
            try:
                with sqlite3.connect(self._database_path) as connection:
                    rows = connection.execute(
                        "SELECT run_id, payload FROM sessions ORDER BY run_id"
                    ).fetchall()
            except sqlite3.Error as exc:
                raise SessionRepositoryError(f"failed to list sessions: {exc}") from exc
        return tuple(self._decode(str(run_id), payload) for run_id, payload in rows)

    @staticmethod
    def _decode(run_id: str, payload: bytes) -> SessionRecord:
        try:
            record = pickle.loads(payload)
        except (pickle.PickleError, EOFError, AttributeError, ValueError, TypeError) as exc:
            raise SessionRepositoryError(f"stored session {run_id} is corrupt") from exc
        if not isinstance(record, SessionRecord):
            raise SessionRepositoryError(f"stored session {run_id} has an invalid record type")
        try:
            return validate_session_record_integrity(record)
        except SessionRepositoryError as exc:
            raise SessionRepositoryError(f"stored session {run_id} failed integrity validation") from exc
