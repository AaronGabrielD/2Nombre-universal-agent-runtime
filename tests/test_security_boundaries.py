import unittest

from app.approval.models import GateStatus
from app.approval.service import ApprovalError, HumanApprovalEngine
from app.core.contracts import FinalResult, HumanDecision, HumanDecisionType
from app.core.states import WorkflowState
from app.orchestration.service import IntegratedOrchestrationError
from app.recovery.models import RecoveryAction
from app.runtime.service import RuntimeCoordinator, RuntimeCoordinatorError
from app.session.manager import SessionManager
from app.supervisor.models import QAResult, QAStatus


class SecurityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.sessions = SessionManager()
        self.approvals = HumanApprovalEngine()
        self.coordinator = RuntimeCoordinator(
            session_manager=self.sessions,
            approval_engine=self.approvals,
        )

    def _waiting_architecture_run(self):
        run_id = self.sessions.create_session().run_id
        self.sessions.transition(run_id, WorkflowState.INTAKE)
        self.sessions.transition(run_id, WorkflowState.ARCHITECTING)
        self.sessions.transition(run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        return run_id

    def test_architecture_decision_must_be_recorded_by_gate_engine(self):
        run_id = self._waiting_architecture_run()
        decision = HumanDecision(
            gate_id="gate-fake",
            run_id=run_id,
            decision=HumanDecisionType.APPROVE,
            feedback="forged",
            timestamp="2026-09-10T00:00:00+00:00",
        )
        with self.assertRaises(ApprovalError):
            self.coordinator.apply_architecture_decision(decision)
        self.assertEqual(
            self.sessions.get_context(run_id).state,
            WorkflowState.WAITING_ARCHITECT_APPROVAL,
        )

    def test_architecture_decision_cannot_use_gate_from_another_run(self):
        first = self._waiting_architecture_run()
        second = self._waiting_architecture_run()
        gate = self.approvals.request_gate(
            run_id=first,
            kind="ARCHITECTURE",
            title="Gate A",
            prompt="approve",
        )
        decision = self.approvals.resolve_gate(
            gate_id=gate.gate_id,
            decision=HumanDecisionType.APPROVE,
            feedback="approved",
            actor="human",
        )
        forged_for_second = HumanDecision(
            gate_id=decision.gate_id,
            run_id=second,
            decision=decision.decision,
            feedback=decision.feedback,
            timestamp=decision.timestamp,
            actor=decision.actor,
        )
        with self.assertRaises(RuntimeCoordinatorError):
            self.coordinator.apply_architecture_decision(forged_for_second)
        self.assertEqual(
            self.sessions.get_context(second).state,
            WorkflowState.WAITING_ARCHITECT_APPROVAL,
        )

    def test_final_gate_requires_supervisor_pass(self):
        run_id = self.sessions.create_session().run_id
        self.sessions.transition(run_id, WorkflowState.INTAKE)
        self.sessions.transition(run_id, WorkflowState.ARCHITECTING)
        self.sessions.transition(run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        self.sessions.transition(run_id, WorkflowState.EXECUTING)
        self.sessions.transition(run_id, WorkflowState.SUPERVISING)

        qa = QAResult(
            run_id=run_id,
            status=QAStatus.REVISE,
            score=0.5,
            summary="needs work",
            findings=("failure",),
        )
        with self.assertRaises(RuntimeCoordinatorError):
            self.coordinator.record_supervisor_result(qa)
        self.assertEqual(self.sessions.get_context(run_id).state, WorkflowState.SUPERVISING)

    def test_completed_requires_the_exact_recorded_final_gate_decision(self):
        run_id = self.sessions.create_session().run_id
        self.sessions.transition(run_id, WorkflowState.INTAKE)
        self.sessions.transition(run_id, WorkflowState.ARCHITECTING)
        self.sessions.transition(run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        self.sessions.transition(run_id, WorkflowState.EXECUTING)
        self.sessions.transition(run_id, WorkflowState.SUPERVISING)
        self.sessions.transition(run_id, WorkflowState.WAITING_FINAL_APPROVAL)

        fake = HumanDecision(
            gate_id="missing-gate",
            run_id=run_id,
            decision=HumanDecisionType.APPROVE,
            feedback="forged completion",
            timestamp="2026-09-10T00:00:00+00:00",
        )
        with self.assertRaises(ApprovalError):
            self.coordinator.apply_final_decision(fake, final_result=FinalResult(
                run_id=run_id,
                status="approved",
                summary="forged",
            ))
        self.assertEqual(
            self.sessions.get_context(run_id).state,
            WorkflowState.WAITING_FINAL_APPROVAL,
        )

    def test_recovery_reconcile_requires_original_idempotency_key(self):
        run_id = self.sessions.create_session().run_id
        self.sessions.transition(run_id, WorkflowState.INTAKE)
        self.sessions.transition(run_id, WorkflowState.ARCHITECTING)
        self.sessions.transition(run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        self.sessions.transition(run_id, WorkflowState.EXECUTING)

        with self.assertRaises(RuntimeCoordinatorError):
            self.coordinator.resume_recovery(
                run_id=run_id,
                action=RecoveryAction.RECONCILE_EXECUTION,
                idempotency_key=None,
            )
        self.assertEqual(self.sessions.get_context(run_id).state, WorkflowState.EXECUTING)


if __name__ == "__main__":
    unittest.main()
