import unittest

from app.core.contracts import (
    ArchitecturePlan,
    ArtifactRef,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    FinalResult,
    HumanDecision,
    HumanDecisionType,
    RiskLevel,
    TaskSpec,
    ToolSpec,
    WorkerSpec,
)
from app.core.exceptions import ContractValidationError


class M31ContractValidationTests(unittest.TestCase):
    def test_worker_rejects_non_string_identity(self):
        with self.assertRaises(ContractValidationError):
            WorkerSpec(1, "builder", "mission").validate()

    def test_worker_rejects_non_string_sequences(self):
        with self.assertRaises(ContractValidationError):
            WorkerSpec(
                "worker",
                "builder",
                "mission",
                deliverables=("ok", 7),
            ).validate()

    def test_architecture_rejects_non_worker_items(self):
        with self.assertRaises(ContractValidationError):
            ArchitecturePlan(
                plan_id="plan",
                objective="objective",
                workers=("not-a-worker",),
            ).validate()

    def test_architecture_rejects_non_positive_worker_limit(self):
        with self.assertRaises(ContractValidationError):
            ArchitecturePlan(
                plan_id="plan",
                objective="objective",
                workers=(WorkerSpec("w", "role", "mission"),),
            ).validate(max_workers=0)

    def test_task_rejects_non_string_description(self):
        with self.assertRaises(ContractValidationError):
            TaskSpec("task", "worker", 123, "output").validate()

    def test_tool_rejects_invalid_schema_and_boolean_fields(self):
        with self.assertRaises(ContractValidationError):
            ToolSpec(
                "tool",
                "Tool",
                "desc",
                input_schema=[],
            ).validate()
        with self.assertRaises(ContractValidationError):
            ToolSpec(
                "tool",
                "Tool",
                "desc",
                requires_human_approval="yes",
            ).validate()

    def test_execution_request_rejects_boolean_timeout(self):
        with self.assertRaises(ContractValidationError):
            ExecutionRequest(
                "execution",
                "run",
                "worker",
                "python",
                "print(1)",
                timeout_seconds=True,
            ).validate()

    def test_execution_request_rejects_non_string_environment(self):
        with self.assertRaises(ContractValidationError):
            ExecutionRequest(
                "execution",
                "run",
                "worker",
                "python",
                "print(1)",
                environment={"TOKEN": 123},
            ).validate()

    def test_artifact_result_and_decision_are_validated(self):
        ArtifactRef("artifact", "file.txt", "text/plain", "artifact://1").validate()
        ExecutionResult(
            execution_id="execution",
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
            artifacts=(ArtifactRef("artifact", "file.txt"),),
            backend="test",
        ).validate()
        HumanDecision(
            gate_id="gate",
            run_id="run",
            decision=HumanDecisionType.APPROVE,
            feedback="approved",
            timestamp="2026-09-09T13:00:00Z",
        ).validate()

    def test_execution_result_rejects_invalid_duration(self):
        with self.assertRaises(ContractValidationError):
            ExecutionResult(
                execution_id="execution",
                status=ExecutionStatus.SUCCESS,
                exit_code=0,
                stdout="",
                stderr="",
                duration_ms=-1,
            ).validate()

    def test_final_result_requires_structured_items(self):
        FinalResult(
            run_id="run",
            status="approved",
            summary="done",
            deliverables=({"name": "x"},),
            tests=({"name": "tests"},),
        ).validate()
        with self.assertRaises(ContractValidationError):
            FinalResult(
                run_id="run",
                status="approved",
                summary="done",
                deliverables=("not-an-object",),
            ).validate()

    def test_medium_risk_tool_does_not_require_gate(self):
        ToolSpec(
            "tool",
            "Tool",
            "desc",
            risk_level=RiskLevel.MEDIUM,
            requires_human_approval=False,
        ).validate()


if __name__ == "__main__":
    unittest.main()
