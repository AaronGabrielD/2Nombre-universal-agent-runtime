"""Stable, provider-neutral contracts shared between runtime modules."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum, StrEnum
from typing import Any

from .exceptions import ContractValidationError


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    worker_id: str
    role: str
    mission: str
    deliverables: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    can_request_human_input: bool = True

    def validate(self) -> None:
        if not self.worker_id.strip(): raise ContractValidationError("worker_id cannot be empty")
        if not self.role.strip(): raise ContractValidationError(f"Worker {self.worker_id}: role cannot be empty")
        if not self.mission.strip(): raise ContractValidationError(f"Worker {self.worker_id}: mission cannot be empty")
        if self.worker_id in self.dependencies: raise ContractValidationError(f"Worker {self.worker_id} cannot depend on itself")


@dataclass(frozen=True, slots=True)
class ArchitecturePlan:
    plan_id: str
    objective: str
    assumptions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    workers: tuple[WorkerSpec, ...] = ()

    def validate(self, *, max_workers: int = 4) -> None:
        if not self.plan_id.strip(): raise ContractValidationError("plan_id cannot be empty")
        if not self.objective.strip(): raise ContractValidationError("objective cannot be empty")
        if not self.workers: raise ContractValidationError("ArchitecturePlan requires at least one worker")
        if len(self.workers) > max_workers: raise ContractValidationError(f"ArchitecturePlan requested {len(self.workers)} workers; maximum is {max_workers}")
        ids = {worker.worker_id for worker in self.workers}
        if len(ids) != len(self.workers): raise ContractValidationError("Worker IDs must be unique")
        for worker in self.workers:
            worker.validate()
            missing = set(worker.dependencies) - ids
            if missing: raise ContractValidationError(f"Worker {worker.worker_id} has unknown dependencies: {sorted(missing)}")


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    worker_id: str
    description: str
    expected_output: str
    required_tools: tuple[str, ...] = ()

    def validate(self) -> None:
        for name, value in (("task_id", self.task_id), ("worker_id", self.worker_id), ("description", self.description), ("expected_output", self.expected_output)):
            if not value.strip(): raise ContractValidationError(f"{name} cannot be empty")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    tool_id: str
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_human_approval: bool = False
    available: bool = True

    def validate(self) -> None:
        if not self.tool_id.strip() or not self.name.strip(): raise ContractValidationError("Tool ID and name are required")
        if self.risk_level == RiskLevel.HIGH and not self.requires_human_approval: raise ContractValidationError(f"High-risk tool {self.tool_id} must require human approval")


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    execution_id: str
    run_id: str
    worker_id: str
    language: str
    code: str
    timeout_seconds: int = 60
    needs_network: bool = False
    environment: dict[str, str] = field(default_factory=dict)

    def validate(self, *, max_timeout_seconds: int = 3600) -> None:
        if not self.execution_id.strip() or not self.run_id.strip() or not self.worker_id.strip(): raise ContractValidationError("execution_id, run_id and worker_id are required")
        if not self.language.strip() or not self.code.strip(): raise ContractValidationError("language and code are required")
        if not 1 <= self.timeout_seconds <= max_timeout_seconds: raise ContractValidationError(f"timeout_seconds must be between 1 and {max_timeout_seconds}")


class ExecutionStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    name: str
    mime_type: str | None = None
    uri: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    execution_id: str
    status: ExecutionStatus
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    artifacts: tuple[ArtifactRef, ...] = ()
    backend: str = "unknown"


class HumanDecisionType(StrEnum):
    APPROVE = "approve"
    MODIFY = "modify"
    REJECT = "reject"
    CLARIFY = "clarify"


@dataclass(frozen=True, slots=True)
class HumanDecision:
    gate_id: str
    run_id: str
    decision: HumanDecisionType
    feedback: str
    timestamp: str
    actor: str = "human"


@dataclass(frozen=True, slots=True)
class FinalResult:
    run_id: str
    status: str
    summary: str
    deliverables: tuple[dict[str, Any], ...] = ()
    tests: tuple[dict[str, Any], ...] = ()
    issues: tuple[str, ...] = ()
    recommended_next_action: str = ""


def to_dict(value: Any) -> Any:
    """Recursively convert runtime contracts to JSON-friendly primitives."""
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: to_dict(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): to_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_dict(item) for item in value]
    return value
