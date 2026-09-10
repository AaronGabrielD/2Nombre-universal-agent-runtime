"""Explicit multi-task execution reconciliation for restart recovery."""
from __future__ import annotations

from dataclasses import dataclass

from app.session.manager import SessionManager

from .lease import ExecutionLease, ExecutionLeaseService
from .reconciliation import ExecutionReconciliation, ExecutionReconciliationService


@dataclass(frozen=True, slots=True)
class RunReconciliation:
    run_id: str
    items: tuple[ExecutionReconciliation, ...]

    @property
    def pending(self) -> tuple[ExecutionReconciliation, ...]:
        return tuple(
            item
            for item in self.items
            if item.status.value
            in {"pending_backend_check", "backend_unavailable", "backend_no_result"}
        )

    @property
    def terminal(self) -> tuple[ExecutionReconciliation, ...]:
        return tuple(
            item for item in self.items if item.status.value in {"completed", "failed"}
        )


class RunExecutionReconciliationService:
    """Enumerate durable leases and reconcile them explicitly, never by replaying execution."""

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
        """Return one reconciliation entry per latest durable lease, without backend calls."""
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
        """Explicitly reconcile every persisted lease through backend authority."""
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
