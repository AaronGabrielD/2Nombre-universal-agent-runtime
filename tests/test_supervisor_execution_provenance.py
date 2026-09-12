from app.core.contracts import ExecutionResult, ExecutionStatus
from app.session.models import WorkerOutput
from app.supervisor.models import QAStatus, SupervisorInput
from app.supervisor.service import SupervisorService


def _input(*, worker_id: str, result_worker_id: str) -> SupervisorInput:
    execution_id = "exec-1"
    return SupervisorInput(
        run_id="run-1",
        objective="execute the task",
        acceptance_criteria=("task completed",),
        worker_outputs=(
            WorkerOutput(
                worker_id=worker_id,
                run_id="run-1",
                status="success",
                output={"execution": {"execution_id": execution_id}},
            ),
        ),
        execution_results=(
            ExecutionResult(
                execution_id=execution_id,
                run_id="run-1",
                worker_id=result_worker_id,
                status=ExecutionStatus.SUCCESS,
                exit_code=0,
                stdout="ok",
                stderr="",
                duration_ms=1,
                backend="test",
            ),
        ),
    )


def test_supervisor_rejects_execution_produced_for_another_worker() -> None:
    result = SupervisorService().evaluate(
        _input(worker_id="worker-a", result_worker_id="worker-b")
    )

    assert result.status == QAStatus.REVISE
    assert any("owners" in issue for issue in result.blocking_issues)


def test_supervisor_accepts_matching_worker_execution_provenance() -> None:
    result = SupervisorService().evaluate(
        _input(worker_id="worker-a", result_worker_id="worker-a")
    )

    assert result.status == QAStatus.PASS
