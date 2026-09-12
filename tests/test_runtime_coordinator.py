import unittest

from app.approval.service import HumanApprovalEngine
from app.architect.models import ArchitectureInput
from app.core.contracts import (
    ArchitecturePlan,
    ExecutionResult,
    ExecutionStatus,
    HumanDecision,
    HumanDecisionType,
    WorkerSpec,
    to_dict,
)
from app.core.states import WorkflowState
from app.intake.service import IntakeService
from app.runtime.service import RuntimeCoordinator, RuntimeCoordinatorError
from app.session.manager import SessionManager
from app.session.models import WorkerOutput
from app.supervisor.models import QAResult, QAStatus, SupervisorInput


class StubArchitect:
    def build_plan(self, request: ArchitectureInput) -> ArchitecturePlan:
        request.validate()
        return ArchitecturePlan(
            plan_id="plan-test",
            objective=request.objective,
            acceptance_criteria=("deliver the requested result",),
            workers=(
                WorkerSpec(
                    worker_id="worker-1",
                    role="builder",
                    mission="produce the deliverable",
                    deliverables=("deliverable",),
                ),
            ),
        )


def make_coordinator():
    sessions = SessionManager()
    approvals = HumanApprovalEngine()
    intake = IntakeService(session_manager=sessions)
    return RuntimeCoordinator(
        session_manager=sessions,
        intake_service=intake,
        architect=StubArchitect(),
        approval_engine=approvals,
    ), sessions, approvals


class RuntimeCoordinatorTests(unittest.TestCase):
    def test_architecture_requires_human_approval_before_execution(self):
        coordinator, sessions, approvals = make_coordinator()
        intake = coordinator.start_run("Build a test project")
        checkpoint = coordinator.build_architecture(intake.run_id)

        self.assertEqual(
            sessions.get_context(intake.run_id).state,
            WorkflowState.WAITING_ARCHITECT_APPROVAL,
        )
        self.assertEqual(len(approvals.list_open_gates(run_id=intake.run_id)), 1)

        fabricated = HumanDecision(
            gate_id=checkpoint.gate_id,
            run_id=intake.run_id,
            decision=HumanDecisionType.APPROVE,
            feedback="not actually recorded",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        with self.assertRaises(RuntimeCoordinatorError):
            coordinator.apply_architecture_decision(fabricated)

        self.assertEqual(
            sessions.get_context(intake.run_id).state,
            WorkflowState.WAITING_ARCHITECT_APPROVAL,
        )
        self.assertEqual(sessions.snapshot(intake.run_id).decisions, [])

    def test_approved_architecture_authorizes_execution_state_only(self):
        coordinator, sessions, approvals = make_coordinator()
        intake = coordinator.start_run("Build a test project")
        checkpoint = coordinator.build_architecture(intake.run_id)

        decision = approvals.resolve_gate(
            gate_id=checkpoint.gate_id,
            decision=HumanDecisionType.APPROVE,
            feedback="Approved.",
        )
        state = coordinator.apply_architecture_decision(decision)

        self.assertEqual(state, WorkflowState.EXECUTING)

    def test_non_pass_cannot_open_final_gate(self):
        coordinator, sessions, _ = make_coordinator()
        intake = coordinator.start_run("Build a test project")
        coordinator.build_architecture(intake.run_id)
        sessions.transition(intake.run_id, WorkflowState.EXECUTING)
        sessions.transition(intake.run_id, WorkflowState.SUPERVISING)

        result = QAResult(
            run_id=intake.run_id,
            status=QAStatus.REVISE,
            score=0.5,
            summary="Needs changes.",
            findings=("missing requirement",),
            blocking_issues=("missing requirement",),
            recommended_action="revise",
            evidence={},
        )
        with self.assertRaises(RuntimeCoordinatorError):
            coordinator.record_supervisor_result(result)

    def test_final_approval_is_the_only_completion_path(self):
        coordinator, sessions, approvals = make_coordinator()
        intake = coordinator.start_run("Build a test project")
        checkpoint = coordinator.build_architecture(intake.run_id)
        first = approvals.resolve_gate(
            gate_id=checkpoint.gate_id,
            decision=HumanDecisionType.APPROVE,
            feedback="Approved.",
        )
        coordinator.apply_architecture_decision(first)
        sessions.add_worker_output(
            intake.run_id,
            WorkerOutput(
                worker_id="worker-1",
                run_id=intake.run_id,
                status="success",
                output={"execution": {"execution_id": "exec-final-test"}},
            ),
        )
        sessions.add_execution_result(
            intake.run_id,
            ExecutionResult(
                execution_id="exec-final-test",
                run_id=intake.run_id,
                worker_id="worker-1",
                status=ExecutionStatus.SUCCESS,
                exit_code=0,
                stdout="ok",
                stderr="",
                duration_ms=1,
                backend="test",
            ),
        )
        sessions.transition(intake.run_id, WorkflowState.SUPERVISING)

        snapshot = sessions.snapshot(intake.run_id)
        plan = snapshot.architecture_plan
        self.assertIsNotNone(plan)
        qa = coordinator.supervisor.evaluate(
            SupervisorInput(
                run_id=intake.run_id,
                objective=plan.objective,
                acceptance_criteria=plan.acceptance_criteria,
                worker_outputs=tuple(snapshot.worker_outputs.values()),
                execution_results=snapshot.execution_results,
                artifacts=tuple(to_dict(artifact) for artifact in snapshot.artifacts),
            )
        )
        self.assertEqual(qa.status, QAStatus.PASS)

        gate_id = coordinator.record_supervisor_result(qa)
        self.assertEqual(
            sessions.get_context(intake.run_id).state,
            WorkflowState.WAITING_FINAL_APPROVAL,
        )

        final_decision = approvals.resolve_gate(
            gate_id=gate_id,
            decision=HumanDecisionType.APPROVE,
            feedback="Approved for completion.",
        )
        state = coordinator.apply_final_decision(final_decision)
        self.assertEqual(state, WorkflowState.COMPLETED)
        self.assertIsNotNone(sessions.snapshot(intake.run_id).final_result)

    def test_cross_run_gate_decision_is_rejected_without_mutating_session(self):
        coordinator, sessions, approvals = make_coordinator()
        run_a = coordinator.start_run("A")
        checkpoint_a = coordinator.build_architecture(run_a.run_id)
        run_b = coordinator.start_run("B")
        checkpoint_b = coordinator.build_architecture(run_b.run_id)

        fabricated = HumanDecision(
            gate_id=checkpoint_a.gate_id,
            run_id=run_b.run_id,
            decision=HumanDecisionType.APPROVE,
            feedback="cross-run",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        with self.assertRaises(RuntimeCoordinatorError):
            coordinator.apply_architecture_decision(fabricated)

        self.assertEqual(
            sessions.get_context(run_b.run_id).state,
            WorkflowState.WAITING_ARCHITECT_APPROVAL,
        )
        self.assertEqual(sessions.snapshot(run_b.run_id).decisions, [])
        self.assertEqual(
            approvals.list_open_gates(run_id=run_a.run_id)[0].gate_id,
            checkpoint_a.gate_id,
        )
        self.assertEqual(
            approvals.list_open_gates(run_id=run_b.run_id)[0].gate_id,
            checkpoint_b.gate_id,
        )


if __name__ == "__main__":
    unittest.main()
