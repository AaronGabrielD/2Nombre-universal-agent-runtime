import unittest

from app.core.states import WorkflowState
from app.recovery.coordinator import RecoveryCoordinator
from app.recovery.models import RecoveryAction
from app.session.manager import SessionManager


class M41RecoveryCoordinatorTests(unittest.TestCase):
    def test_plan_marks_human_gate_as_non_automatic(self):
        sessions = SessionManager()
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)

        plan = RecoveryCoordinator(session_manager=sessions).plan(run.run_id)
        self.assertEqual(plan.action, RecoveryAction.AWAIT_ARCHITECT_APPROVAL)
        self.assertTrue(plan.requires_human)
        self.assertTrue(plan.resumable)

    def test_plan_marks_terminal_as_not_resumable(self):
        sessions = SessionManager()
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        sessions.transition(run.run_id, WorkflowState.REJECTED)

        plan = RecoveryCoordinator(session_manager=sessions).plan(run.run_id)
        self.assertEqual(plan.action, RecoveryAction.TERMINAL)
        self.assertFalse(plan.resumable)


if __name__ == "__main__":
    unittest.main()
