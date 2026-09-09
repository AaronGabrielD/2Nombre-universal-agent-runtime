"""Classify persisted runs for safe, explicit post-restart recovery."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock

from app.core.states import TERMINAL_STATES, WorkflowState
from app.session.manager import SessionManager
from app.session.repository import SessionNotFoundError

from .models import RecoveryAction, RecoveryCheckpoint


class RecoveryServiceError(ValueError):
    """Raised when a recovery operation cannot be performed safely."""


class RecoveryService:
    """Inspect durable runs and produce non-executing recovery checkpoints."""

    def __init__(self, *, session_manager: SessionManager) -> None:
        self.sessions = session_manager
        self._lock = RLock()

    def inspect(self, run_id: str) -> RecoveryCheckpoint:
        """Classify one persisted run without changing state or executing work."""
        with self._lock:
            try:
                record = self.sessions.snapshot(run_id)
            except SessionNotFoundError as exc:
                raise RecoveryServiceError(f"unknown run_id: {run_id}") from exc
            checkpoint = self._checkpoint(record)
            checkpoint.validate()
            return deepcopy(checkpoint)

    def list_checkpoints(self) -> tuple[RecoveryCheckpoint, ...]:
        """Return checkpoints for all persisted runs in deterministic run_id order."""
        with self._lock:
            return tuple(self._checkpoint(record) for record in self.sessions.list_sessions())

    @staticmethod
    def _checkpoint(record) -> RecoveryCheckpoint:
        state = record.context.state
        if state in TERMINAL_STATES:
            action = RecoveryAction.TERMINAL
            safe = False
            reason = "Run is terminal and must not be resumed."
        elif state == WorkflowState.ARCHITECTING:
            action = RecoveryAction.REBUILD_ARCHITECTURE
            safe = False
            reason = "Architecture must be rebuilt or restored explicitly before execution."
        elif state == WorkflowState.WAITING_ARCHITECT_APPROVAL:
            action = RecoveryAction.AWAIT_ARCHITECT_APPROVAL
            safe = False
            reason = "A human architecture decision is still required."
        elif state == WorkflowState.WORKER_WAITING_HUMAN:
            action = RecoveryAction.AWAIT_HUMAN_GATE
            safe = False
            reason = "A human worker/tool gate is outstanding; no execution may be replayed."
        elif state == WorkflowState.EXECUTING:
            action = RecoveryAction.RECONCILE_EXECUTION
            safe = False
            reason = "An execution may have been in flight when the process stopped; reconcile evidence before retrying."
        elif state == WorkflowState.SUPERVISING:
            action = RecoveryAction.RESUME_SUPERVISION
            safe = False
            reason = "Persisted worker evidence can be supplied to supervision explicitly."
        elif state == WorkflowState.WAITING_FINAL_APPROVAL:
            action = RecoveryAction.AWAIT_FINAL_APPROVAL
            safe = False
            reason = "The final human approval gate remains authoritative."
        elif state == WorkflowState.REVISION:
            action = RecoveryAction.REBUILD_ARCHITECTURE
            safe = False
            reason = "Revision requires a new architecture cycle."
        else:
            raise RecoveryServiceError(f"unsupported recovery state: {state.value}")

        return RecoveryCheckpoint(
            run_id=record.context.run_id,
            state=state,
            action=action,
            safe_to_automatically_execute=safe,
            execution_result_count=len(record.execution_results),
            worker_output_count=len(record.worker_outputs),
            message_count=len(record.messages),
            reason=reason,
        )
