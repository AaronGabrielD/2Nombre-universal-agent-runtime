"""Deterministic supervisor/QA service for M09."""
from __future__ import annotations

from app.core.contracts import ExecutionStatus

from .models import QAResult, QAStatus, SupervisorInput


class SupervisorError(RuntimeError):
    """Raised when supervisor input or invariants are invalid."""


class SupervisorService:
    """Evaluate worker/execution evidence without mutating session state."""

    SUCCESS_STATUSES = {"success", "completed", "ok"}
    FAILURE_EXECUTION_STATUSES = {
        ExecutionStatus.ERROR,
        ExecutionStatus.TIMEOUT,
        ExecutionStatus.DENIED,
        ExecutionStatus.UNAVAILABLE,
    }

    def evaluate(self, data: SupervisorInput) -> QAResult:
        try:
            data.validate()
        except (ValueError, AttributeError, TypeError) as exc:
            raise SupervisorError(str(exc)) from exc

        findings: list[str] = []
        blocking: list[str] = []
        worker_ids = [item.worker_id for item in data.worker_outputs]
        execution_ids = {result.execution_id for result in data.execution_results}
        evidence = {
            "worker_count": len(worker_ids),
            "execution_count": len(data.execution_results),
            "acceptance_criteria_count": len(data.acceptance_criteria),
        }

        invalid_run_results = [
            result.execution_id
            for result in data.execution_results
            if result.run_id != data.run_id
        ]
        if invalid_run_results:
            blocking.append(
                f"Execution evidence belongs to another run: {sorted(invalid_run_results)}"
            )

        duplicate_execution_ids = [
            execution_id
            for execution_id in sorted(execution_ids)
            if sum(result.execution_id == execution_id for result in data.execution_results) > 1
        ]
        if duplicate_execution_ids:
            blocking.append(
                f"Duplicate execution evidence was supplied: {duplicate_execution_ids}"
            )

        duplicate_worker_ids = [
            worker_id
            for worker_id in sorted(set(worker_ids))
            if worker_ids.count(worker_id) > 1
        ]
        if duplicate_worker_ids:
            blocking.append("Duplicate worker evidence was supplied.")
        if not data.worker_outputs:
            blocking.append("No worker outputs were produced.")

        failed_workers = [
            item.worker_id
            for item in data.worker_outputs
            if not isinstance(item.status, str)
            or item.status.lower() not in self.SUCCESS_STATUSES
        ]
        if failed_workers:
            blocking.append(
                f"Workers did not complete successfully: {sorted(failed_workers)}"
            )

        execution_failures = [
            result
            for result in data.execution_results
            if result.status in self.FAILURE_EXECUTION_STATUSES
        ]
        if execution_failures:
            blocking.append(
                f"{len(execution_failures)} execution result(s) are not successful."
            )

        missing_execution_evidence: list[str] = []
        mismatched_execution_workers: list[str] = []
        unattributed_execution_workers: list[str] = []
        referenced_execution_ids: set[str] = set()
        for item in data.worker_outputs:
            if item.status.lower() not in self.SUCCESS_STATUSES:
                continue
            execution = item.output.get("execution") if isinstance(item.output, dict) else None
            execution_id = execution.get("execution_id") if isinstance(execution, dict) else None
            if execution_id not in execution_ids:
                missing_execution_evidence.append(item.worker_id)
                continue
            if execution_id in referenced_execution_ids:
                blocking.append(
                    f"Multiple workers reference the same execution evidence: {execution_id}"
                )
                mismatched_execution_workers.append(item.worker_id)
                continue
            referenced_execution_ids.add(execution_id)
            matching_results = [
                result for result in data.execution_results if result.execution_id == execution_id
            ]
            if not matching_results:
                missing_execution_evidence.append(item.worker_id)
                continue
            result = matching_results[0]
            if result.run_id != data.run_id or result.status != ExecutionStatus.SUCCESS:
                mismatched_execution_workers.append(item.worker_id)
                continue
            if result.worker_id != item.worker_id:
                unattributed_execution_workers.append(item.worker_id)

        if missing_execution_evidence:
            blocking.append(
                "Successful workers lack attributable execution evidence: "
                f"{sorted(missing_execution_evidence)}"
            )
        if mismatched_execution_workers:
            blocking.append(
                "Successful workers reference non-successful or duplicated execution evidence: "
                f"{sorted(mismatched_execution_workers)}"
            )
        if unattributed_execution_workers:
            blocking.append(
                "Successful workers are not the owners of their execution evidence: "
                f"{sorted(unattributed_execution_workers)}"
            )

        if not data.acceptance_criteria:
            findings.append(
                "No acceptance criteria were supplied; qualitative completion cannot be fully verified."
            )

        evidence["failed_worker_ids"] = sorted(failed_workers)
        evidence["failed_execution_count"] = len(execution_failures)
        evidence["invalid_execution_run_ids"] = sorted(invalid_run_results)
        evidence["duplicate_execution_ids"] = duplicate_execution_ids
        evidence["missing_execution_evidence_workers"] = sorted(missing_execution_evidence)
        evidence["mismatched_execution_workers"] = sorted(mismatched_execution_workers)
        evidence["unattributed_execution_workers"] = sorted(unattributed_execution_workers)

        if blocking:
            status = (
                QAStatus.REVISE
                if failed_workers
                or execution_failures
                or missing_execution_evidence
                or mismatched_execution_workers
                or unattributed_execution_workers
                else QAStatus.FAIL
            )
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
