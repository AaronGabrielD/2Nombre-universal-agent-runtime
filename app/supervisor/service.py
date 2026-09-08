"""Deterministic supervisor/QA service for M09."""
from __future__ import annotations

from app.core.contracts import ExecutionStatus

from .models import QAResult, QAStatus, SupervisorInput


class SupervisorError(RuntimeError):
    """Raised when supervisor input or invariants are invalid."""


class SupervisorService:
    """Evaluate worker/execution evidence without mutating session state."""

    def evaluate(self, data: SupervisorInput) -> QAResult:
        try:
            data.validate()
        except ValueError as exc:
            raise SupervisorError(str(exc)) from exc

        findings: list[str] = []
        blocking: list[str] = []
        evidence = {
            "worker_count": len(data.worker_outputs),
            "execution_count": len(data.execution_results),
            "acceptance_criteria_count": len(data.acceptance_criteria),
        }

        if not data.worker_outputs:
            blocking.append("No worker outputs were produced.")

        failed_workers = [
            item.worker_id
            for item in data.worker_outputs
            if item.status.lower() not in {"success", "completed", "ok"}
        ]
        if failed_workers:
            blocking.append(
                f"Workers did not complete successfully: {sorted(failed_workers)}"
            )

        execution_failures = [
            result
            for result in data.execution_results
            if result.status
            in {
                ExecutionStatus.ERROR,
                ExecutionStatus.TIMEOUT,
                ExecutionStatus.DENIED,
                ExecutionStatus.UNAVAILABLE,
            }
        ]
        if execution_failures:
            blocking.append(
                f"{len(execution_failures)} execution result(s) are not successful."
            )

        if not data.acceptance_criteria:
            findings.append(
                "No acceptance criteria were supplied; qualitative completion cannot be fully verified."
            )

        evidence["failed_worker_ids"] = sorted(failed_workers)
        evidence["failed_execution_count"] = len(execution_failures)

        if blocking:
            status = QAStatus.REVISE if failed_workers or execution_failures else QAStatus.FAIL
            score = 0.0
            summary = "The run is not ready for final approval."
            recommended = "revise_and_reexecute"
        elif not data.acceptance_criteria:
            status = QAStatus.REVISE
            score = 0.75
            summary = "Execution completed, but acceptance criteria are missing."
            recommended = "define_acceptance_criteria_and_review"
        else:
            status = QAStatus.PASS
            score = 1.0
            summary = "Deterministic QA checks passed; the run may proceed to final human approval."
            recommended = "request_final_human_approval"

        result = QAResult(
            run_id=data.run_id,
            status=status,
            score=score,
            summary=summary,
            findings=tuple(findings),
            blocking_issues=tuple(blocking),
            recommended_action=recommended,
            evidence=evidence,
        )
        result.validate()
        return result
