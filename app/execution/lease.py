"""Durable execution leases preventing unsafe replay after restart."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
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
    """Persist execution-lease state in session history; never stores executable code."""

    PHASE = "execution_lease"

    def __init__(self, *, session_manager: SessionManager) -> None:
        self.sessions = session_manager
        self._lock = RLock()

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
            existing = self._find(run_id, idempotency_key)
            if existing is not None:
                if existing.status == "COMPLETED":
                    return existing
                raise ExecutionLeaseError(
                    f"execution lease already active for idempotency key {idempotency_key}"
                )
            lease = ExecutionLease(
                lease_id=str(uuid4()),
                run_id=run_id,
                worker_id=worker_id,
                task_id=task_id,
                idempotency_key=idempotency_key,
                execution_id=execution_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self.sessions.add_message(
                run_id,
                role="system",
                content=f"Execution lease reserved for worker {worker_id}, task {task_id}",
                metadata={
                    "phase": self.PHASE,
                    "lease_id": lease.lease_id,
                    "worker_id": worker_id,
                    "task_id": task_id,
                    "idempotency_key": idempotency_key,
                    "execution_id": execution_id,
                    "status": lease.status,
                    "timestamp": lease.timestamp,
                },
            )
            return lease

    def complete(self, *, run_id: str, lease_id: str) -> ExecutionLease:
        with self._lock:
            current = self._find_by_lease(run_id, lease_id)
            if current is None:
                raise ExecutionLeaseError(f"unknown execution lease: {lease_id}")
            if current.status == "COMPLETED":
                return current
            completed = ExecutionLease(
                **{**current.__dict__, "status": "COMPLETED", "timestamp": datetime.now(timezone.utc).isoformat()}
            )
            self.sessions.add_message(
                run_id,
                role="system",
                content=f"Execution lease completed: {lease_id}",
                metadata={
                    "phase": self.PHASE,
                    "lease_id": lease_id,
                    "worker_id": current.worker_id,
                    "task_id": current.task_id,
                    "idempotency_key": current.idempotency_key,
                    "execution_id": current.execution_id,
                    "status": completed.status,
                    "timestamp": completed.timestamp,
                },
            )
            return completed

    def get(self, *, run_id: str, idempotency_key: str) -> ExecutionLease | None:
        with self._lock:
            return self._find(run_id, idempotency_key)

    def _find(self, run_id: str, idempotency_key: str) -> ExecutionLease | None:
        for message in reversed(self.sessions.snapshot(run_id).messages):
            metadata = message.metadata
            if metadata.get("phase") != self.PHASE or metadata.get("idempotency_key") != idempotency_key:
                continue
            return ExecutionLease(
                lease_id=str(metadata["lease_id"]),
                run_id=run_id,
                worker_id=str(metadata["worker_id"]),
                task_id=str(metadata["task_id"]),
                idempotency_key=idempotency_key,
                execution_id=str(metadata["execution_id"]),
                status=str(metadata["status"]),
                timestamp=str(metadata["timestamp"]),
            )
        return None

    def _find_by_lease(self, run_id: str, lease_id: str) -> ExecutionLease | None:
        for message in reversed(self.sessions.snapshot(run_id).messages):
            metadata = message.metadata
            if metadata.get("phase") != self.PHASE or metadata.get("lease_id") != lease_id:
                continue
            return ExecutionLease(
                lease_id=lease_id,
                run_id=run_id,
                worker_id=str(metadata["worker_id"]),
                task_id=str(metadata["task_id"]),
                idempotency_key=str(metadata["idempotency_key"]),
                execution_id=str(metadata["execution_id"]),
                status=str(metadata["status"]),
                timestamp=str(metadata["timestamp"]),
            )
        return None
