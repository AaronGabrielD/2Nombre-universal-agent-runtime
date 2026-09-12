"""Durable execution leases preventing unsafe replay after restart."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import sqlite3
from threading import RLock
from uuid import uuid4

from app.session.manager import SessionManager


class ExecutionLeaseError(ValueError):
    """Raised when an execution lease cannot be safely acquired or completed."""


@dataclass(frozen=True, slots=True)
class ExecutionLease:
    lease_id: str
    run_id: str
    worker_id: str
    task_id: str
    idempotency_key: str
    execution_id: str
    status: str = "RUNNING"
    timestamp: str = ""


class ExecutionLeaseService:
    """Persist execution leases and atomically enforce idempotency on SQLite."""

    PHASE = "execution_lease"

    def __init__(self, *, session_manager: SessionManager) -> None:
        self.sessions = session_manager
        self._lock = RLock()
        repository = session_manager.repository
        self._sqlite_path = getattr(repository, "_database_path", None)
        if isinstance(self._sqlite_path, str) and self._sqlite_path.strip():
            try:
                with sqlite3.connect(self._sqlite_path) as connection:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS execution_leases (
                            lease_id TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL,
                            worker_id TEXT NOT NULL,
                            task_id TEXT NOT NULL,
                            idempotency_key TEXT NOT NULL,
                            execution_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            timestamp TEXT NOT NULL,
                            UNIQUE(run_id, idempotency_key)
                        )
                        """
                    )
                    connection.execute(
                        "CREATE INDEX IF NOT EXISTS idx_execution_leases_run ON execution_leases(run_id)"
                    )
            except sqlite3.Error as exc:
                raise ExecutionLeaseError(f"failed to initialize durable execution leases: {exc}") from exc

    @staticmethod
    def idempotency_key(*, run_id: str, worker_id: str, task_id: str, language: str, code: str) -> str:
        material = "\x1f".join((run_id, worker_id, task_id, language, code))
        return sha256(material.encode("utf-8")).hexdigest()

    def reserve(
        self,
        *,
        run_id: str,
        worker_id: str,
        task_id: str,
        idempotency_key: str,
        execution_id: str,
    ) -> ExecutionLease:
        fields = (run_id, worker_id, task_id, idempotency_key, execution_id)
        if not all(isinstance(value, str) and value.strip() for value in fields):
            raise ExecutionLeaseError("execution lease identifiers cannot be empty")
        with self._lock:
            if self._sqlite_path:
                return self._reserve_sqlite(
                    run_id=run_id,
                    worker_id=worker_id,
                    task_id=task_id,
                    idempotency_key=idempotency_key,
                    execution_id=execution_id,
                )

            existing = self._find(run_id, idempotency_key)
            if existing is not None:
                if existing.status == "COMPLETED":
                    return existing
                raise ExecutionLeaseError(
                    f"execution lease already active for idempotency key {idempotency_key}"
                )
            lease = self._new_lease(
                run_id=run_id,
                worker_id=worker_id,
                task_id=task_id,
                idempotency_key=idempotency_key,
                execution_id=execution_id,
            )
            self._audit_reservation(lease)
            return lease

    def _reserve_sqlite(self, **fields: str) -> ExecutionLease:
        lease = self._new_lease(**fields)
        try:
            with sqlite3.connect(self._sqlite_path) as connection:
                connection.execute(
                    """
                    INSERT INTO execution_leases
                    (lease_id, run_id, worker_id, task_id, idempotency_key, execution_id, status, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lease.lease_id,
                        lease.run_id,
                        lease.worker_id,
                        lease.task_id,
                        lease.idempotency_key,
                        lease.execution_id,
                        lease.status,
                        lease.timestamp,
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self._sqlite_get(fields["run_id"], fields["idempotency_key"])
            if existing is None:
                raise ExecutionLeaseError("execution lease uniqueness conflict could not be resolved")
            if existing.status == "COMPLETED":
                return existing
            raise ExecutionLeaseError(
                f"execution lease already active for idempotency key {fields['idempotency_key']}"
            )
        except sqlite3.Error as exc:
            raise ExecutionLeaseError(f"failed to reserve durable execution lease: {exc}") from exc
        try:
            self._audit_reservation(lease)
        except Exception as exc:
            try:
                with sqlite3.connect(self._sqlite_path) as connection:
                    connection.execute("DELETE FROM execution_leases WHERE lease_id = ?", (lease.lease_id,))
            except sqlite3.Error:
                pass
            raise ExecutionLeaseError(f"failed to audit execution lease: {exc}") from exc
        return lease

    def _new_lease(self, **fields: str) -> ExecutionLease:
        return ExecutionLease(
            lease_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            **fields,
        )

    def complete(self, *, run_id: str, lease_id: str) -> ExecutionLease:
        with self._lock:
            if self._sqlite_path:
                current = self._sqlite_get_by_lease(run_id, lease_id)
            else:
                current = self._find_by_lease(run_id, lease_id)
            if current is None:
                raise ExecutionLeaseError(f"unknown execution lease: {lease_id}")
            if current.status == "COMPLETED":
                return current
            completed = replace(
                current,
                status="COMPLETED",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            if self._sqlite_path:
                try:
                    with sqlite3.connect(self._sqlite_path) as connection:
                        connection.execute(
                            "UPDATE execution_leases SET status = ?, timestamp = ? WHERE lease_id = ? AND run_id = ?",
                            (completed.status, completed.timestamp, lease_id, run_id),
                        )
                except sqlite3.Error as exc:
                    raise ExecutionLeaseError(f"failed to complete durable execution lease: {exc}") from exc
            self._audit_completion(completed)
            return completed

    def get(self, *, run_id: str, idempotency_key: str) -> ExecutionLease | None:
        with self._lock:
            if self._sqlite_path:
                return self._sqlite_get(run_id, idempotency_key)
            return self._find(run_id, idempotency_key)

    def _sqlite_get(self, run_id: str, idempotency_key: str) -> ExecutionLease | None:
        try:
            with sqlite3.connect(self._sqlite_path) as connection:
                row = connection.execute(
                    "SELECT lease_id, run_id, worker_id, task_id, idempotency_key, execution_id, status, timestamp FROM execution_leases WHERE run_id = ? AND idempotency_key = ?",
                    (run_id, idempotency_key),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ExecutionLeaseError(f"failed to read durable execution lease: {exc}") from exc
        return self._row_to_lease(row) if row else None

    def _sqlite_get_by_lease(self, run_id: str, lease_id: str) -> ExecutionLease | None:
        try:
            with sqlite3.connect(self._sqlite_path) as connection:
                row = connection.execute(
                    "SELECT lease_id, run_id, worker_id, task_id, idempotency_key, execution_id, status, timestamp FROM execution_leases WHERE run_id = ? AND lease_id = ?",
                    (run_id, lease_id),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ExecutionLeaseError(f"failed to read durable execution lease: {exc}") from exc
        return self._row_to_lease(row) if row else None

    @staticmethod
    def _row_to_lease(row: tuple[object, ...]) -> ExecutionLease:
        try:
            values = [str(value) for value in row]
            if len(values) != 8 or values[6] not in {"RUNNING", "COMPLETED"}:
                raise ValueError("invalid stored lease row")
            return ExecutionLease(*values)
        except (TypeError, ValueError) as exc:
            raise ExecutionLeaseError("stored execution lease is invalid") from exc

    def _audit_reservation(self, lease: ExecutionLease) -> None:
        self.sessions.add_message(
            lease.run_id,
            role="system",
            content=f"Execution lease reserved for worker {lease.worker_id}, task {lease.task_id}",
            metadata={
                "phase": self.PHASE,
                "lease_id": lease.lease_id,
                "worker_id": lease.worker_id,
                "task_id": lease.task_id,
                "idempotency_key": lease.idempotency_key,
                "execution_id": lease.execution_id,
                "status": lease.status,
                "timestamp": lease.timestamp,
            },
        )

    def _audit_completion(self, lease: ExecutionLease) -> None:
        self.sessions.add_message(
            lease.run_id,
            role="system",
            content=f"Execution lease completed: {lease.lease_id}",
            metadata={
                "phase": self.PHASE,
                "lease_id": lease.lease_id,
                "worker_id": lease.worker_id,
                "task_id": lease.task_id,
                "idempotency_key": lease.idempotency_key,
                "execution_id": lease.execution_id,
                "status": lease.status,
                "timestamp": lease.timestamp,
            },
        )

    def _find(self, run_id: str, idempotency_key: str) -> ExecutionLease | None:
        for message in reversed(self.sessions.snapshot(run_id).messages):
            metadata = message.metadata
            if metadata.get("phase") != self.PHASE or metadata.get("idempotency_key") != idempotency_key:
                continue
            return self._from_metadata(run_id, metadata)
        return None

    def _find_by_lease(self, run_id: str, lease_id: str) -> ExecutionLease | None:
        for message in reversed(self.sessions.snapshot(run_id).messages):
            metadata = message.metadata
            if metadata.get("phase") != self.PHASE or metadata.get("lease_id") != lease_id:
                continue
            return self._from_metadata(run_id, metadata)
        return None

    @staticmethod
    def _from_metadata(run_id: str, metadata: dict[str, object]) -> ExecutionLease:
        try:
            return ExecutionLease(
                lease_id=str(metadata["lease_id"]),
                run_id=run_id,
                worker_id=str(metadata["worker_id"]),
                task_id=str(metadata["task_id"]),
                idempotency_key=str(metadata["idempotency_key"]),
                execution_id=str(metadata["execution_id"]),
                status=str(metadata["status"]),
                timestamp=str(metadata["timestamp"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionLeaseError("stored execution lease metadata is invalid") from exc
