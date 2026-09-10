"""Explicit recovery actions that never replay execution implicitly."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.core.states import WorkflowState
from app.execution.reconciliation import (
    ExecutionReconciliation,
    ExecutionReconciliationService,
    ReconciliationStatus,
)
from app.session.manager import SessionManager

from .models import RecoveryAction, RecoveryCheckpoint
from .service import RecoveryService


class RecoveryResumeError(ValueError):
    """Raised when an explicit recovery action is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class RecoveryResumeResult:
    run_id: str
    checkpoint: RecoveryCheckpoint
    resulting_state: WorkflowState
    reconciliation: ExecutionReconciliation | None = None
    audit_event_id: str = ""


class RecoveryResumeService:
    """Apply only explicit, non-ambiguous recovery transitions."""

    AUDIT_PHASE = "recovery_resume"

    def __init__(
        self,
        *,
        session_manager: SessionManager,
        reconciliation_service: ExecutionReconciliationService | None = None,
    ) -> None:
        self.sessions = session_manager
        self.recovery = RecoveryService(session_manager=session_manager)
        self.reconciliation = reconciliation_service or ExecutionReconciliationService(
            session_manager=session_manager
        )

    def inspect(self, run_id: str) -> RecoveryCheckpoint:
        return self.recovery.inspect(run_id)

    def resume(
        self,
        *,
        run_id: str,
        action: RecoveryAction,
        idempotency_key: str | None = None,
    ) -> RecoveryResumeResult:
        checkpoint = self.recovery.inspect(run_id)
        if checkpoint.action != action:
            raise RecoveryResumeError(
                f"recovery action mismatch: checkpoint requires {checkpoint.action.value}, got {action.value}"
            )
        if action == RecoveryAction.TERMINAL:
            raise RecoveryResumeError("terminal runs cannot be resumed")

        state = self.sessions.get_context(run_id).state
        previous_state = state
        if action == RecoveryAction.REBUILD_ARCHITECTURE:
            if state == WorkflowState.REVISION:
                state = self.sessions.transition(run_id, WorkflowState.ARCHITECTING).state
            elif state != WorkflowState.ARCHITECTING:
                raise RecoveryResumeError(
                    f"architecture rebuild requires ARCHITECTING or REVISION, got {state.value}"
                )
            audit_event_id = self._record_audit(
                run_id=run_id,
                action=action,
                previous_state=previous_state,
                resulting_state=state,
            )
            return RecoveryResumeResult(run_id, checkpoint, state, audit_event_id=audit_event_id)

        if action in {
            RecoveryAction.AWAIT_ARCHITECT_APPROVAL,
            RecoveryAction.AWAIT_HUMAN_GATE,
            RecoveryAction.AWAIT_FINAL_APPROVAL,
        }:
            audit_event_id = self._record_audit(
                run_id=run_id,
                action=action,
                previous_state=previous_state,
                resulting_state=state,
            )
            return RecoveryResumeResult(run_id, checkpoint, state, audit_event_id=audit_event_id)

        if action == RecoveryAction.RESUME_SUPERVISION:
            if state != WorkflowState.SUPERVISING:
                raise RecoveryResumeError(f"supervision resume requires SUPERVISING, got {state.value}")
            audit_event_id = self._record_audit(
                run_id=run_id,
                action=action,
                previous_state=previous_state,
                resulting_state=state,
            )
            return RecoveryResumeResult(run_id, checkpoint, state, audit_event_id=audit_event_id)

        if action == RecoveryAction.RECONCILE_EXECUTION:
            if not idempotency_key:
                raise RecoveryResumeError("execution reconciliation requires idempotency_key")
            result = self.reconciliation.inspect(run_id=run_id, idempotency_key=idempotency_key)
            if result.status == ReconciliationStatus.PENDING_BACKEND_CHECK:
                result = self.reconciliation.reconcile_backend(
                    run_id=run_id,
                    idempotency_key=idempotency_key,
                )
            if result.status == ReconciliationStatus.COMPLETED:
                if state == WorkflowState.EXECUTING:
                    state = self.sessions.transition(run_id, WorkflowState.SUPERVISING).state
                audit_event_id = self._record_audit(
                    run_id=run_id,
                    action=action,
                    previous_state=previous_state,
                    resulting_state=state,
                    reconciliation=result,
                )
                return RecoveryResumeResult(run_id, checkpoint, state, result, audit_event_id)
            if result.status == ReconciliationStatus.FAILED:
                if state == WorkflowState.EXECUTING:
                    state = self.sessions.transition(run_id, WorkflowState.REVISION).state
                audit_event_id = self._record_audit(
                    run_id=run_id,
                    action=action,
                    previous_state=previous_state,
                    resulting_state=state,
                    reconciliation=result,
                )
                return RecoveryResumeResult(run_id, checkpoint, state, result, audit_event_id)
            raise RecoveryResumeError(
                f"execution reconciliation did not establish terminal evidence: {result.status.value}"
            )

        raise RecoveryResumeError(f"unsupported recovery action: {action.value}")

    def _record_audit(
        self,
        *,
        run_id: str,
        action: RecoveryAction,
        previous_state: WorkflowState,
        resulting_state: WorkflowState,
        reconciliation: ExecutionReconciliation | None = None,
    ) -> str:
        event_id = str(uuid4())
        metadata = {
            "phase": self.AUDIT_PHASE,
            "event_id": event_id,
            "action": action.value,
            "previous_state": previous_state.value,
            "resulting_state": resulting_state.value,
            "outcome": "accepted",
        }
        if reconciliation is not None:
            metadata["reconciliation_status"] = reconciliation.status.value
            metadata["execution_id"] = reconciliation.execution_id
        self.sessions.add_message(
            run_id,
            role="system",
            content=f"Recovery action accepted: {action.value}",
            metadata=metadata,
        )
        return event_id
