"""Provider-neutral reconciliation of persisted execution leases."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.execution.lease import ExecutionLeaseService
from app.session.manager import SessionManager
from app.session.repository import SessionNotFoundError


class ReconciliationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING_BACKEND_CHECK = "pending_backend_check"
    NO_LEASE = "no_lease"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    BACKEND_NO_RESULT = "backend_no_result"


@dataclass(frozen=True, slots=True)
class ExecutionReconciliation:
    run_id: str
    worker_id: str
    task_id: str
    execution_id: str
    status: ReconciliationStatus
    detail: str
    result: ExecutionResult | None = None


class ExecutionReconciler(ABC):
    """Explicit backend-side authority used only during reconciliation."""

    @abstractmethod
    def reconcile(self, *, execution_id: str, idempotency_key: str) -> ExecutionResult | None:
        raise NotImplementedError


class ExecutionReconciliationService:
    """Reconcile durable local evidence, with optional explicit backend authority."""

    def __init__(self, *, session_manager: SessionManager, backend_reconciler: ExecutionReconciler | None = None) -> None:
        self.sessions = session_manager
        self.leases = ExecutionLeaseService(session_manager=session_manager)
        self.backend_reconciler = backend_reconciler

    def inspect(self, *, run_id: str, idempotency_key: str) -> ExecutionReconciliation:
        try:
            record = self.sessions.snapshot(run_id)
        except SessionNotFoundError as exc:
            raise ValueError(f"unknown run_id: {run_id}") from exc

        lease = self.leases.get(run_id=run_id, idempotency_key=idempotency_key)
        if lease is None:
            return ExecutionReconciliation(run_id=run_id, worker_id="", task_id="", execution_id="", status=ReconciliationStatus.NO_LEASE, detail="No durable execution lease exists for this idempotency key.")

        local = self._find_local_result(record.execution_results, lease.execution_id)
        if local is not None:
            return self._from_result(lease, local)

        return ExecutionReconciliation(
            run_id=run_id,
            worker_id=lease.worker_id,
            task_id=lease.task_id,
            execution_id=lease.execution_id,
            status=ReconciliationStatus.PENDING_BACKEND_CHECK,
            detail="A lease exists without a persisted result; explicit backend-side reconciliation is required before retrying.",
        )

    def reconcile_backend(self, *, run_id: str, idempotency_key: str) -> ExecutionReconciliation:
        """Ask the explicitly supplied backend reconciler for authoritative evidence."""
        local = self.inspect(run_id=run_id, idempotency_key=idempotency_key)
        if local.status in {ReconciliationStatus.COMPLETED, ReconciliationStatus.FAILED, ReconciliationStatus.NO_LEASE}:
            return local
        if self.backend_reconciler is None:
            return ExecutionReconciliation(
                run_id=local.run_id,
                worker_id=local.worker_id,
                task_id=local.task_id,
                execution_id=local.execution_id,
                status=ReconciliationStatus.BACKEND_UNAVAILABLE,
                detail="No backend reconciliation capability was explicitly configured.",
            )

        result = self.backend_reconciler.reconcile(execution_id=local.execution_id, idempotency_key=idempotency_key)
        if result is None:
            return ExecutionReconciliation(
                run_id=local.run_id,
                worker_id=local.worker_id,
                task_id=local.task_id,
                execution_id=local.execution_id,
                status=ReconciliationStatus.BACKEND_NO_RESULT,
                detail="The backend reconciler returned no authoritative result; retry is not permitted.",
            )
        if result.execution_id != local.execution_id:
            raise ValueError("backend reconciliation returned an inconsistent execution_id")
        return self._from_result(local, result)

    @staticmethod
    def _find_local_result(results: tuple[ExecutionResult, ...], execution_id: str) -> ExecutionResult | None:
        for result in reversed(results):
            if result.execution_id == execution_id:
                return result
        return None

    @staticmethod
    def _from_result(owner, result: ExecutionResult) -> ExecutionReconciliation:
        if result.status == ExecutionStatus.SUCCESS:
            status = ReconciliationStatus.COMPLETED
            detail = "Execution evidence confirms successful completion."
        else:
            status = ReconciliationStatus.FAILED
            detail = f"Execution evidence confirms terminal status: {result.status.value}."
        return ExecutionReconciliation(run_id=owner.run_id, worker_id=owner.worker_id, task_id=owner.task_id, execution_id=result.execution_id, status=status, detail=detail, result=result)
