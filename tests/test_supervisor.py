from __future__ import annotations

import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.session.models import WorkerOutput
from app.supervisor import QAStatus, SupervisorInput, SupervisorService


def execution(status=ExecutionStatus.SUCCESS):
    return ExecutionResult(
        execution_id="exec-1",
        status=status,
        exit_code=0 if status == ExecutionStatus.SUCCESS else None,
        stdout="ok" if status == ExecutionStatus.SUCCESS else "",
        stderr="",
        duration_ms=1,
        backend="test",
    )


class SupervisorTests(unittest.TestCase):
    def test_passes_successful_run_with_criteria(self):
        result = SupervisorService().evaluate(
            SupervisorInput(
                run_id="run-1",
                objective="Build feature",
                acceptance_criteria=("tests pass",),
                worker_outputs=(WorkerOutput("worker-1", "run-1", "success", "done"),),
                execution_results=(execution(),),
            )
        )
        self.assertEqual(result.status, QAStatus.PASS)
        self.assertEqual(result.recommended_action, "request_final_human_approval")
        self.assertEqual(result.score, 1.0)

    def test_revise_when_worker_failed(self):
        result = SupervisorService().evaluate(
            SupervisorInput(
                run_id="run-1",
                objective="Build feature",
                acceptance_criteria=("tests pass",),
                worker_outputs=(WorkerOutput("worker-1", "run-1", "failed", "broken"),),
                execution_results=(execution(),),
            )
        )
        self.assertEqual(result.status, QAStatus.REVISE)
        self.assertTrue(result.blocking_issues)

    def test_revise_when_execution_failed(self):
        result = SupervisorService().evaluate(
            SupervisorInput(
                run_id="run-1",
                objective="Build feature",
                acceptance_criteria=("tests pass",),
                worker_outputs=(WorkerOutput("worker-1", "run-1", "success", "done"),),
                execution_results=(execution(ExecutionStatus.TIMEOUT),),
            )
        )
        self.assertEqual(result.status, QAStatus.REVISE)
        self.assertEqual(result.evidence["failed_execution_count"], 1)

    def test_revise_when_acceptance_criteria_are_missing(self):
        result = SupervisorService().evaluate(
            SupervisorInput(
                run_id="run-1",
                objective="Build feature",
                worker_outputs=(WorkerOutput("worker-1", "run-1", "success", "done"),),
                execution_results=(execution(),),
            )
        )
        self.assertEqual(result.status, QAStatus.REVISE)
        self.assertIn("acceptance criteria", result.findings[0].lower())

    def test_missing_workers_is_blocking(self):
        result = SupervisorService().evaluate(
            SupervisorInput(
                run_id="run-1",
                objective="Build feature",
                acceptance_criteria=("tests pass",),
                execution_results=(execution(),),
            )
        )
        self.assertEqual(result.status, QAStatus.FAIL)
        self.assertTrue(result.blocking_issues)

    def test_invalid_input_raises_supervisor_error(self):
        with self.assertRaises(Exception):
            SupervisorService().evaluate(SupervisorInput(run_id="", objective="x"))


if __name__ == "__main__":
    unittest.main()
