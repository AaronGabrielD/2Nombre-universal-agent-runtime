"""Provider-neutral M09 supervisor and QA contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.contracts import ExecutionResult
from app.session.models import WorkerOutput


class QAStatus(StrEnum):
    PASS = "pass"
    REVISE = "revise"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class SupervisorInput:
    run_id: str
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    worker_outputs: tuple[WorkerOutput, ...] = ()
    execution_results: tuple[ExecutionResult, ...] = ()
    artifacts: tuple[dict[str, Any], ...] = ()

    def validate(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ValueError("objective cannot be empty")
        if not isinstance(self.acceptance_criteria, (tuple, list)) or any(
            not isinstance(item, str) or not item.strip() for item in self.acceptance_criteria
        ):
            raise ValueError("acceptance_criteria must contain non-empty strings")
        if not isinstance(self.worker_outputs, (tuple, list)) or any(
            not isinstance(item, WorkerOutput) for item in self.worker_outputs
        ):
            raise ValueError("worker_outputs must contain WorkerOutput instances")
        if not isinstance(self.execution_results, (tuple, list)) or any(
            not isinstance(item, ExecutionResult) for item in self.execution_results
        ):
            raise ValueError("execution_results must contain ExecutionResult instances")
        if not isinstance(self.artifacts, (tuple, list)) or any(
            not isinstance(item, dict) for item in self.artifacts
        ):
            raise ValueError("artifacts must contain mappings")
        for result in self.execution_results:
            result.validate()
        for output in self.worker_outputs:
            if output.run_id != self.run_id:
                raise ValueError("worker output belongs to another run")


@dataclass(frozen=True, slots=True)
class QAResult:
    run_id: str
    status: QAStatus
    score: float
    summary: str
    findings: tuple[str, ...] = ()
    blocking_issues: tuple[str, ...] = ()
    recommended_action: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not isinstance(self.status, QAStatus):
            try:
                QAStatus(self.status)
            except (TypeError, ValueError) as exc:
                raise ValueError("status must be a valid QAStatus") from exc
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise ValueError("score must be numeric")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("score must be between 0 and 1")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("summary cannot be empty")
        for name, values in (
            ("findings", self.findings),
            ("blocking_issues", self.blocking_issues),
        ):
            if not isinstance(values, (tuple, list)) or any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                raise ValueError(f"{name} must contain non-empty strings")
        if not isinstance(self.recommended_action, str):
            raise ValueError("recommended_action must be a string")
        if not isinstance(self.evidence, dict):
            raise ValueError("evidence must be a mapping")
        if self.status == QAStatus.FAIL and not self.blocking_issues:
            raise ValueError("failed QA results require blocking issues")
