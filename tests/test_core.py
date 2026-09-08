import unittest

from app.core.contracts import (
    ArchitecturePlan,
    ExecutionRequest,
    ExecutionStatus,
    ToolSpec,
    WorkerSpec,
    RiskLevel,
)
from app.core.exceptions import ContractValidationError, IllegalStateTransition
from app.core.models import RunContext
from app.core.states import WorkflowState


class StateMachineTests(unittest.TestCase):
    def test_valid_flow_transition(self):
        run = RunContext()
        run.transition_to(WorkflowState.INTAKE)
        run.transition_to(WorkflowState.ARCHITECTING)
        run.transition_to(WorkflowState.WAITING_ARCHITECT_APPROVAL)
        self.assertEqual(run.state, WorkflowState.WAITING_ARCHITECT_APPROVAL)

    def test_illegal_transition_is_rejected(self):
        run = RunContext()
        with self.assertRaises(IllegalStateTransition):
            run.transition_to(WorkflowState.COMPLETED)


class ContractTests(unittest.TestCase):
    def test_architecture_plan_validates(self):
        plan = ArchitecturePlan(
            plan_id="p1",
            objective="Solve a technical problem",
            workers=(
                WorkerSpec(
                    worker_id="w1",
                    role="Researcher",
                    mission="Research the problem",
                ),
            ),
        )
        plan.validate(max_workers=4)

    def test_architecture_plan_rejects_duplicate_worker_ids(self):
        plan = ArchitecturePlan(
            plan_id="p1",
            objective="Test",
            workers=(
                WorkerSpec("w1", "A", "A"),
                WorkerSpec("w1", "B", "B"),
            ),
        )
        with self.assertRaises(ContractValidationError):
            plan.validate()

    def test_execution_request_rejects_empty_code(self):
        request = ExecutionRequest(
            execution_id="e1",
            run_id="r1",
            worker_id="w1",
            language="python",
            code="",
        )
        with self.assertRaises(ContractValidationError):
            request.validate()

    def test_high_risk_tool_requires_human_approval(self):
        tool = ToolSpec(
            tool_id="shell",
            name="Shell",
            description="Execute shell commands",
            risk_level=RiskLevel.HIGH,
            requires_human_approval=False,
        )
        with self.assertRaises(ContractValidationError):
            tool.validate()

    def test_execution_status_values_are_stable(self):
        self.assertEqual(ExecutionStatus.SUCCESS.value, "success")
        self.assertEqual(ExecutionStatus.TIMEOUT.value, "timeout")


if __name__ == "__main__":
    unittest.main()
