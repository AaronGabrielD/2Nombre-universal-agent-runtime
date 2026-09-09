"""Stable, provider-neutral contracts shared between runtime modules."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum, StrEnum
from typing import Any

from .contracts_validation import (
    require_non_empty_string,
    require_non_negative_integer,
    require_object_mapping,
    require_positive_integer,
    require_string_mapping,
    require_string_sequence,
)
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
        require_non_empty_string("worker_id", self.worker_id)
        require_non_empty_string(f"Worker {self.worker_id}: role", self.role)
        require_non_empty_string(f"Worker {self.worker_id}: mission", self.mission)
        require_string_sequence(f"Worker {self.worker_id}: deliverables", self.deliverables)
        require_string_sequence(f"Worker {self.worker_id}: required_tools", self.required_tools)
        require_string_sequence(f"Worker {self.worker_id}: dependencies", self.dependencies)
        if not isinstance(self.can_request_human_input, bool):
            raise ContractValidationError(
                f"Worker {self.worker_id}: can_request_human_input must be a boolean"
            )
        if self.worker_id in self.dependencies:
            raise ContractValidationError(f"Worker {self.worker_id} cannot depend on itself")


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
        require_non_empty_string("plan_id", self.plan_id)
        require_non_empty_string("objective", self.objective)
        require_positive_integer("max_workers", max_workers)
        require_string_sequence("assumptions", self.assumptions)
        require_string_sequence("constraints", self.constraints)
        require_string_sequence("acceptance_criteria", self.acceptance_criteria)
        require_string_sequence("risks", self.risks)
        require_string_sequence("required_capabilities", self.required_capabilities)
        if not isinstance(self.workers, (tuple, list)) or not self.workers:
            raise ContractValidationError("ArchitecturePlan requires at least one worker")
        if len(self.workers) > max_workers:
            raise ContractValidationError(
                f"ArchitecturePlan requested {len(self.workers)} workers; maximum is {max_workers}"
            )
        if any(not isinstance(worker, WorkerSpec) for worker in self.workers):
            raise ContractValidationError("ArchitecturePlan workers must be WorkerSpec instances")
        ids = {worker.worker_id for worker in self.workers}
        if len(ids) != len(self.workers):
            raise ContractValidationError("Worker IDs must be unique")
        for worker in self.workers:
            worker.validate()
            missing = set(worker.dependencies) - ids
            if missing:
                raise ContractValidationError(
                    f"Worker {worker.worker_id} has unknown dependencies: {sorted(missing)}"
                )


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    worker_id: str
    description: str
    expected_output: str
    required_tools: tuple[str, ...] = ()

    def validate(self) -> None:
        require_non_empty_string("task_id", self.task_id)
        require_non_empty_string("worker_id", self.worker_id)
        require_non_empty_string("description", self.description)
        require_non_empty_string("expected_output", self.expected_output)
        require_string_sequence("required_tools", self.required_tools)


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
        require_non_empty_string("tool_id", self.tool_id)
        require_non_empty_string("name", self.name)
        require_non_empty_string("description", self.description)
        require_object_mapping("input_schema", self.input_schema)
        require_object_mapping("output_schema", self.output_schema)
        if not isinstance(self.risk_level, RiskLevel):
            try:
                RiskLevel(self.risk_level)
            except (TypeError, ValueError) as exc:
                raise ContractValidationError("risk_level must be low, medium, or high") from exc
        if not isinstance(self.requires_human_approval, bool):
            raise ContractValidationError("requires_human_approval must be a boolean")
        if not isinstance(self.available, bool):
            raise ContractValidationError("available must be a boolean")
        if self.risk_level == RiskLevel.HIGH and not self.requires_human_approval:
            raise ContractValidationError(
                f"High-risk tool {self.tool_id} must require human approval"
            )


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
        require_non_empty_string("execution_id", self.execution_id)
        require_non_empty_string("run_id", self.run_id)
        require_non_empty_string("worker_id", self.worker_id)
        require_non_empty_string("language", self.language)
        require_non_empty_string("code", self.code)
        require_positive_integer("max_timeout_seconds", max_timeout_seconds)
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, int):
            raise ContractValidationError("timeout_seconds must be an integer")
        if not 1 <= self.timeout_seconds <= max_timeout_seconds:
            raise ContractValidationError(
                f"timeout_seconds must be between 1 and {max_timeout_seconds}"
            )
        if not isinstance(self.needs_network, bool):
            raise ContractValidationError("needs_network must be a boolean")
        require_string_mapping("environment", self.environment)


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

    def validate(self) -> None:
        require_non_empty_string("artifact_id", self.artifact_id)
        require_non_empty_string("name", self.name)
        if self.mime_type is not None:
            require_non_empty_string("mime_type", self.mime_type)
        if self.uri is not None:
            require_non_empty_string("uri", self.uri)


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

    def validate(self) -> None:
        require_non_empty_string("execution_id", self.execution_id)
        if not isinstance(self.status, ExecutionStatus):
            try:
                ExecutionStatus(self.status)
            except (TypeError, ValueError) as exc:
                raise ContractValidationError("status is not a valid ExecutionStatus") from exc
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise ContractValidationError("exit_code must be an integer or None")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise ContractValidationError("stdout and stderr must be strings")
        require_non_negative_integer("duration_ms", self.duration_ms)
        if not isinstance(self.artifacts, (tuple, list)):
            raise ContractValidationError("artifacts must be a tuple/list of ArtifactRef")
        for artifact in self.artifacts:
            if not isinstance(artifact, ArtifactRef):
                raise ContractValidationError("artifacts must contain ArtifactRef instances")
            artifact.validate()
        require_non_empty_string("backend", self.backend)


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

    def validate(self) -> None:
        require_non_empty_string("gate_id", self.gate_id)
        require_non_empty_string("run_id", self.run_id)
        if not isinstance(self.decision, HumanDecisionType):
            try:
                HumanDecisionType(self.decision)
            except (TypeError, ValueError) as exc:
                raise ContractValidationError("decision is not a valid HumanDecisionType") from exc
        if not isinstance(self.feedback, str):
            raise ContractValidationError("feedback must be a string")
        require_non_empty_string("timestamp", self.timestamp)
        require_non_empty_string("actor", self.actor)


@dataclass(frozen=True, slots=True)
class FinalResult:
    run_id: str
    status: str
    summary: str
    deliverables: tuple[dict[str, Any], ...] = ()
    tests: tuple[dict[str, Any], ...] = ()
    issues: tuple[str, ...] = ()
    recommended_next_action: str = ""

    def validate(self) -> None:
        require_non_empty_string("run_id", self.run_id)
        require_non_empty_string("status", self.status)
        require_non_empty_string("summary", self.summary)
        if not isinstance(self.deliverables, (tuple, list)):
            raise ContractValidationError("deliverables must be a tuple/list")
        if not isinstance(self.tests, (tuple, list)):
            raise ContractValidationError("tests must be a tuple/list")
        require_string_sequence("issues", self.issues)
        if not isinstance(self.recommended_next_action, str):
            raise ContractValidationError("recommended_next_action must be a string")
        for name, values in (("deliverables", self.deliverables), ("tests", self.tests)):
            for index, item in enumerate(values):
                if not isinstance(item, dict):
                    raise ContractValidationError(f"{name}[{index}] must be an object mapping")


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
