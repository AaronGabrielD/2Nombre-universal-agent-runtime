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
        if not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not self.objective.strip():
            raise ValueError("objective cannot be empty")


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
        if not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0 and 1")
        if not self.summary.strip():
            raise ValueError("summary cannot be empty")
        if self.status == QAStatus.FAIL and not self.blocking_issues:
            raise ValueError("failed QA results require blocking issues")
