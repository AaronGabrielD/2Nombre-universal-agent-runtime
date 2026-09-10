"""Coordinator-facing recovery decisions built on explicit checkpoints."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core.states import WorkflowState
from app.session.manager import SessionManager

from .models import RecoveryAction, RecoveryCheckpoint
from .resume import RecoveryResumeResult, RecoveryResumeService


class RecoveryCoordinatorError(ValueError):
    """Raised when a recovery checkpoint cannot be coordinated safely."""


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    run_id: str
    checkpoint: RecoveryCheckpoint
    action: RecoveryAction
    requires_human: bool
    resumable: bool


class RecoveryCoordinator:
    """Translate persisted recovery checkpoints into explicit coordinator decisions."""

    def __init__(self, *, session_manager: SessionManager, resume_service: RecoveryResumeService | None = None) -> None:
        self.sessions = session_manager
        self.resume_service = resume_service or RecoveryResumeService(session_manager=session_manager)

    def plan(self, run_id: str) -> RecoveryPlan:
        checkpoint = self.resume_service.inspect(run_id)
        requires_human = checkpoint.action in {
            RecoveryAction.AWAIT_ARCHITECT_APPROVAL,
            RecoveryAction.AWAIT_HUMAN_GATE,
            RecoveryAction.AWAIT_FINAL_APPROVAL,
        }
        return RecoveryPlan(
            run_id=run_id,
            checkpoint=checkpoint,
            action=checkpoint.action,
            requires_human=requires_human,
            resumable=checkpoint.action != RecoveryAction.TERMINAL,
        )

    def apply(
        self,
        *,
        run_id: str,
        action: RecoveryAction,
        idempotency_key: str | None = None,
        supervision_callback: Callable[[str], None] | None = None,
    ) -> RecoveryResumeResult:
        """Apply one explicitly selected recovery action and optionally notify supervision."""
        plan = self.plan(run_id)
        if not plan.resumable:
            raise RecoveryCoordinatorError("terminal recovery checkpoints are not resumable")
        result = self.resume_service.resume(
            run_id=run_id,
            action=action,
            idempotency_key=idempotency_key,
        )
        if result.resulting_state == WorkflowState.SUPERVISING and supervision_callback is not None:
            supervision_callback(run_id)
        return result
