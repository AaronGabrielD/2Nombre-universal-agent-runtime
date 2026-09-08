"""Workflow state machine for one universal agent run."""
from __future__ import annotations

from enum import StrEnum

from .exceptions import IllegalStateTransition


class WorkflowState(StrEnum):
    IDLE = "IDLE"
    INTAKE = "INTAKE"
    ARCHITECTING = "ARCHITECTING"
    WAITING_ARCHITECT_APPROVAL = "WAITING_ARCHITECT_APPROVAL"
    EXECUTING = "EXECUTING"
    WORKER_WAITING_HUMAN = "WORKER_WAITING_HUMAN"
    SUPERVISING = "SUPERVISING"
    WAITING_FINAL_APPROVAL = "WAITING_FINAL_APPROVAL"
    REVISION = "REVISION"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


TERMINAL_STATES = {
    WorkflowState.COMPLETED,
    WorkflowState.REJECTED,
    WorkflowState.FAILED,
}

_ALLOWED: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.IDLE: {WorkflowState.INTAKE, WorkflowState.FAILED},
    WorkflowState.INTAKE: {WorkflowState.ARCHITECTING, WorkflowState.FAILED},
    WorkflowState.ARCHITECTING: {
        WorkflowState.WAITING_ARCHITECT_APPROVAL,
        WorkflowState.FAILED,
    },
    WorkflowState.WAITING_ARCHITECT_APPROVAL: {
        WorkflowState.ARCHITECTING,
        WorkflowState.EXECUTING,
        WorkflowState.REJECTED,
        WorkflowState.FAILED,
    },
    WorkflowState.EXECUTING: {
        WorkflowState.EXECUTING,
        WorkflowState.WORKER_WAITING_HUMAN,
        WorkflowState.SUPERVISING,
        WorkflowState.FAILED,
    },
    WorkflowState.WORKER_WAITING_HUMAN: {
        WorkflowState.EXECUTING,
        WorkflowState.FAILED,
    },
    WorkflowState.SUPERVISING: {
        WorkflowState.WAITING_FINAL_APPROVAL,
        WorkflowState.REVISION,
        WorkflowState.FAILED,
    },
    WorkflowState.WAITING_FINAL_APPROVAL: {
        WorkflowState.REVISION,
        WorkflowState.COMPLETED,
        WorkflowState.REJECTED,
        WorkflowState.FAILED,
    },
    WorkflowState.REVISION: {
        WorkflowState.ARCHITECTING,
        WorkflowState.EXECUTING,
        WorkflowState.SUPERVISING,
        WorkflowState.FAILED,
    },
    WorkflowState.COMPLETED: set(),
    WorkflowState.REJECTED: set(),
    WorkflowState.FAILED: set(),
}


def transition_allowed(current: WorkflowState, target: WorkflowState) -> bool:
    """Return whether a transition is explicitly allowed by the state machine."""
    return target in _ALLOWED[current]


def ensure_transition(current: WorkflowState, target: WorkflowState) -> None:
    """Raise if the requested state transition is not legal."""
    if not transition_allowed(current, target):
        raise IllegalStateTransition(f"Illegal transition: {current} -> {target}")


def is_terminal(state: WorkflowState) -> bool:
    """Return whether the workflow has reached a terminal state."""
    return state in TERMINAL_STATES
