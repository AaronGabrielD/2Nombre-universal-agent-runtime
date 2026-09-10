import json
import os
import unittest

from app.core.config import get_settings
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
    to_dict,
)
from app.core.exceptions import ContractValidationError, IllegalStateTransition
from app.core.models import RunContext
from app.core.states import TERMINAL_STATES, WorkflowState, is_terminal, transition_allowed


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

    def test_complete_state_rejects_further_transition(self):
        run = RunContext(state=WorkflowState.COMPLETED)
        with self.assertRaises(IllegalStateTransition):
            run.transition_to(WorkflowState.INTAKE)

    def test_all_terminal_states_are_terminal(self):
        self.assertEqual(
            TERMINAL_STATES,
            {WorkflowState.COMPLETED, WorkflowState.REJECTED, WorkflowState.FAILED},
        )
        for state in WorkflowState:
            self.assertEqual(is_terminal(state), state in TERMINAL_STATES)

    def test_critical_illegal_state_transitions_are_rejected(self):
        illegal_pairs = (
            (WorkflowState.IDLE, WorkflowState.COMPLETED),
            (WorkflowState.INTAKE, WorkflowState.EXECUTING),
            (WorkflowState.ARCHITECTING, WorkflowState.EXECUTING),
            (WorkflowState.SUPERVISING, WorkflowState.COMPLETED),
            (WorkflowState.WAITING_FINAL_APPROVAL, WorkflowState.EXECUTING),
            (WorkflowState.COMPLETED, WorkflowState.ARCHITECTING),
            (WorkflowState.REJECTED, WorkflowState.INTAKE),
            (WorkflowState.FAILED, WorkflowState.EXECUTING),
        )
        for current, target in illegal_pairs:
            self.assertFalse(transition_allowed(current, target), (current, target))
            run = RunContext(state=current)
            with self.assertRaises(IllegalStateTransition):
                run.transition_to(target)

    def test_supported_revision_paths_are_explicit(self):
        self.assertTrue(transition_allowed(WorkflowState.SUPERVISING, WorkflowState.REVISION))
        self.assertTrue(transition_allowed(WorkflowState.WAITING_FINAL_APPROVAL, WorkflowState.REVISION))
        self.assertTrue(transition_allowed(WorkflowState.WORKER_WAITING_HUMAN, WorkflowState.REVISION))
        self.assertTrue(transition_allowed(WorkflowState.REVISION, WorkflowState.ARCHITECTING))


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

    def test_architecture_plan_rejects_empty_workers(self):
        plan = ArchitecturePlan(plan_id="p1", objective="Test", workers=())
        with self.assertRaises(ContractValidationError):
            plan.validate()

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

    def test_architecture_plan_rejects_unknown_dependencies(self):
        plan = ArchitecturePlan(
            plan_id="p1",
            objective="Test",
            workers=(WorkerSpec("w1", "A", "A", dependencies=("missing",)),),
        )
        with self.assertRaises(ContractValidationError):
            plan.validate()

    def test_worker_rejects_self_dependency(self):
        worker = WorkerSpec("w1", "A", "A", dependencies=("w1",))
        with self.assertRaises(ContractValidationError):
            worker.validate()

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

    def test_execution_request_rejects_invalid_timeout(self):
        request = ExecutionRequest("e1", "r1", "w1", "python", "print(1)", timeout_seconds=0)
        with self.assertRaises(ContractValidationError):
            request.validate()
        request = ExecutionRequest("e1", "r1", "w1", "python", "print(1)", timeout_seconds=61)
        with self.assertRaises(ContractValidationError):
            request.validate(max_timeout_seconds=60)

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

    def test_tool_spec_accepts_valid_high_risk_tool_when_approved(self):
        tool = ToolSpec(
            tool_id="tool-high",
            name="High Risk",
            description="Controlled high-risk action",
            risk_level=RiskLevel.HIGH,
            requires_human_approval=True,
        )
        tool.validate()

    def test_human_decision_validates_and_serializes(self):
        decision = HumanDecision(
            gate_id="gate-1",
            run_id="run-1",
            decision=HumanDecisionType.APPROVE,
            feedback="ok",
            timestamp="2026-09-10T00:00:00Z",
        )
        decision.validate()
        payload = to_dict(decision)
        self.assertEqual(payload["decision"], "approve")
        json.dumps(payload)

    def test_human_decision_rejects_invalid_decision(self):
        decision = HumanDecision(
            gate_id="gate-1",
            run_id="run-1",
            decision="invalid",  # type: ignore[arg-type]
            feedback="",
            timestamp="2026-09-10T00:00:00Z",
        )
        with self.assertRaises(ContractValidationError):
            decision.validate()

    def test_final_result_validates_and_serializes(self):
        result = FinalResult(
            run_id="run-1",
            status="ready",
            summary="done",
            deliverables=({"name": "artifact"},),
            tests=({"name": "unit", "status": "pass"},),
            issues=(),
        )
        result.validate()
        payload = to_dict(result)
        self.assertEqual(payload["status"], "ready")
        json.dumps(payload)

    def test_final_result_rejects_non_object_deliverable(self):
        result = FinalResult(
            run_id="run-1",
            status="ready",
            summary="done",
            deliverables=("invalid",),  # type: ignore[arg-type]
        )
        with self.assertRaises(ContractValidationError):
            result.validate()

    def test_execution_result_validates_with_artifact(self):
        result = ExecutionResult(
            execution_id="e1",
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=12,
            artifacts=(ArtifactRef("a1", "result.txt", "text/plain", "artifact://a1"),),
            backend="docker",
        )
        result.validate()

    def test_execution_result_rejects_negative_duration(self):
        result = ExecutionResult(
            execution_id="e1",
            status=ExecutionStatus.ERROR,
            exit_code=1,
            stdout="",
            stderr="error",
            duration_ms=-1,
            backend="docker",
        )
        with self.assertRaises(ContractValidationError):
            result.validate()

    def test_task_spec_rejects_empty_expected_output(self):
        task = TaskSpec("t1", "w1", "do work", "")
        with self.assertRaises(ContractValidationError):
            task.validate()

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
