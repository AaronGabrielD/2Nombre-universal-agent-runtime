import json
import os
import unittest

from app.core.config import get_settings
from app.core.contracts import (
    ArchitecturePlan,
    ExecutionRequest,
    ExecutionStatus,
    RiskLevel,
    ToolSpec,
    WorkerSpec,
    to_dict,
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

    def test_rejected_tool_gate_can_enter_revision(self):
        run = RunContext(state=WorkflowState.WORKER_WAITING_HUMAN)
        run.transition_to(WorkflowState.REVISION)
        self.assertEqual(run.state, WorkflowState.REVISION)

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

    def test_configuration_hides_secrets_from_repr(self):
        previous = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "super-secret-test-key"
        try:
            settings = get_settings(reload=True)
            self.assertNotIn("super-secret-test-key", repr(settings))
        finally:
            if previous is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = previous
            get_settings(reload=True)

    def test_contract_serialization_is_json_friendly(self):
        request = ExecutionRequest("e1", "r1", "w1", "python", "print(1)")
        payload = to_dict(request)
        self.assertEqual(payload["execution_id"], "e1")
        json.dumps(payload)

    def test_execution_status_values_are_stable(self):
        self.assertEqual(ExecutionStatus.SUCCESS.value, "success")
        self.assertEqual(ExecutionStatus.TIMEOUT.value, "timeout")


if __name__ == "__main__":
    unittest.main()
