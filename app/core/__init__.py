"""Core contracts and runtime primitives."""

from .config import Settings, get_settings
from .contracts import (
    ArchitecturePlan,
    ArtifactRef,
    ExecutionRequest,
    ExecutionResult,
    FinalResult,
    HumanDecision,
    TaskSpec,
    ToolSpec,
    WorkerSpec,
)
from .exceptions import ContractValidationError, IllegalStateTransition, RuntimeConfigurationError
from .models import EventRecord, RunContext
from .states import WorkflowState, is_terminal, transition_allowed

__all__ = [
    "ArchitecturePlan",
    "ArtifactRef",
    "ContractValidationError",
    "EventRecord",
    "ExecutionRequest",
    "ExecutionResult",
    "FinalResult",
    "HumanDecision",
    "IllegalStateTransition",
    "RunContext",
    "RuntimeConfigurationError",
    "Settings",
    "TaskSpec",
    "ToolSpec",
    "WorkerSpec",
    "WorkflowState",
    "get_settings",
    "is_terminal",
    "transition_allowed",
]
