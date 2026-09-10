"""Explicit multi-task execution reconciliation for restart recovery."""
from __future__ import annotations

from dataclasses import dataclass

from app.session.manager import SessionManager

from .lease import ExecutionLease, ExecutionLeaseService
from .reconciliation import (
    ExecutionReconciliation,
    ExecutionReconciliationService,
    ReconciliationStatus,
)


@dataclass(frozen=True, slots=True)
class RunReconciliation:
    """Deterministic reconciliation snapshot for every latest lease in one run."""

    run_id: str
    items: tuple[ExecutionReconciliation, ...]

    @property
    def pending(self) -> tuple[ExecutionReconciliation, ...]:
        return tuple(
            item
            for item in self.items
            if item.status
            in {
                ReconciliationStatus.PENDING_BACKEND_CHECK,
                ReconciliationStatus.BACKEND_UNAVAILABLE,
                ReconciliationStatus.BACKEND_NO_RESULT,
            }
        )

    @property
    def terminal(self) -> tuple[ExecutionReconciliation, ...]:
        return tuple(
            item
            for item in self.items
            if item.status in {ReconciliationStatus.COMPLETED, ReconciliationStatus.FAILED}
        )


class RunExecutionReconciliationService:
    """Reconcile every durable execution lease explicitly, without replaying execution."""

    def __init__(
        self,
        *,
        session_manager: SessionManager,
        reconciliation_service: ExecutionReconciliationService | None = None,
    ) -> None:
        self.sessions = session_manager
        self.reconciliation = reconciliation_service or ExecutionReconciliationService(
            session_manager=session_manager
        )

    def inspect(self, run_id: str) -> RunReconciliation:
        """Inspect every latest durable lease without contacting backend authority."""
        snapshot = self.sessions.snapshot(run_id)
        leases = self._latest_leases(snapshot.messages, run_id)
        return RunReconciliation(
            run_id=run_id,
            items=tuple(
                self.reconciliation.inspect(
                    run_id=run_id,
                    idempotency_key=lease.idempotency_key,
                )
                for lease in leases
            ),
        )

    def reconcile_backend(self, run_id: str) -> RunReconciliation:
        """Explicitly reconcile every latest persisted lease through configured authority."""
        snapshot = self.sessions.snapshot(run_id)
        leases = self._latest_leases(snapshot.messages, run_id)
        return RunReconciliation(
            run_id=run_id,
            items=tuple(
                self.reconciliation.reconcile_backend(
                    run_id=run_id,
                    idempotency_key=lease.idempotency_key,
                )
                for lease in leases
            ),
        )

    @staticmethod
    def _latest_leases(messages, run_id: str) -> tuple[ExecutionLease, ...]:
        latest: dict[str, ExecutionLease] = {}
        for message in messages:
            metadata = message.metadata
            if metadata.get("phase") != ExecutionLeaseService.PHASE:
                continue
            key = metadata.get("idempotency_key")
            if not isinstance(key, str) or not key.strip():
                continue
            latest[key] = ExecutionLeaseService._from_metadata(run_id, metadata)
        return tuple(
            sorted(
                latest.values(),
                key=lambda lease: (lease.worker_id, lease.task_id, lease.idempotency_key),
            )
        )
