"""Models for explicit post-restart recovery decisions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.states import WorkflowState


class RecoveryAction(StrEnum):
    REBUILD_ARCHITECTURE = "rebuild_architecture"
    AWAIT_ARCHITECT_APPROVAL = "await_architect_approval"
    AWAIT_HUMAN_GATE = "await_human_gate"
    RESUME_SUPERVISION = "resume_supervision"
    AWAIT_FINAL_APPROVAL = "await_final_approval"
    RECONCILE_EXECUTION = "reconcile_execution"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class RecoveryCheckpoint:
    run_id: str
    state: WorkflowState
    action: RecoveryAction
    safe_to_automatically_execute: bool
    execution_result_count: int
    worker_output_count: int
    message_count: int
    reason: str

    def validate(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not isinstance(self.state, WorkflowState):
            raise ValueError("state must be a WorkflowState")
        if not isinstance(self.action, RecoveryAction):
            raise ValueError("action must be a RecoveryAction")
        if not isinstance(self.safe_to_automatically_execute, bool):
            raise ValueError("safe_to_automatically_execute must be boolean")
        for name, value in {
            "execution_result_count": self.execution_result_count,
            "worker_output_count": self.worker_output_count,
            "message_count": self.message_count,
        }.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason cannot be empty")
