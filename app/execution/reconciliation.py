"""Provider-neutral reconciliation of persisted execution leases."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.contracts import ExecutionStatus
from app.execution.lease import ExecutionLeaseService
from app.session.manager import SessionManager
from app.session.repository import SessionNotFoundError


class ReconciliationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING_BACKEND_CHECK = "pending_backend_check"
    NO_LEASE = "no_lease"


@dataclass(frozen=True, slots=True)
class ExecutionReconciliation:
    run_id: str
    worker_id: str
    task_id: str
    execution_id: str
    status: ReconciliationStatus
    detail: str


class ExecutionReconciliationService:
    """Reconcile a task from durable local evidence without calling a backend."""

    def __init__(self, *, session_manager: SessionManager) -> None:
        self.sessions = session_manager
        self.leases = ExecutionLeaseService(session_manager=session_manager)

    def inspect(
        self,
        *,
        run_id: str,
        idempotency_key: str,
    ) -> ExecutionReconciliation:
        try:
            record = self.sessions.snapshot(run_id)
        except SessionNotFoundError as exc:
            raise ValueError(f"unknown run_id: {run_id}") from exc

        lease = self.leases.get(run_id=run_id, idempotency_key=idempotency_key)
        if lease is None:
            return ExecutionReconciliation(
                run_id=run_id,
                worker_id="",
                task_id="",
                execution_id="",
                status=ReconciliationStatus.NO_LEASE,
                detail="No durable execution lease exists for this idempotency key.",
            )

        for result in reversed(record.execution_results):
            if result.execution_id != lease.execution_id:
                continue
            if result.status == ExecutionStatus.SUCCESS:
                status = ReconciliationStatus.COMPLETED
                detail = "Persisted execution result confirms successful completion."
            else:
                status = ReconciliationStatus.FAILED
                detail = f"Persisted execution result confirms terminal status: {result.status.value}."
            return ExecutionReconciliation(
                run_id=run_id,
                worker_id=lease.worker_id,
                task_id=lease.task_id,
                execution_id=lease.execution_id,
                status=status,
                detail=detail,
            )

        return ExecutionReconciliation(
            run_id=run_id,
            worker_id=lease.worker_id,
            task_id=lease.task_id,
            execution_id=lease.execution_id,
            status=ReconciliationStatus.PENDING_BACKEND_CHECK,
            detail="A lease exists without a persisted result; backend-side reconciliation is required before retrying.",
        )
