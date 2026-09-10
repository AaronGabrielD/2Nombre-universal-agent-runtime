import unittest

from app.core.states import WorkflowState
from app.recovery import RecoveryCoordinator, RecoveryCoordinatorError
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

    def test_terminal_plan_is_not_resumable_and_cannot_apply(self):
        sessions = SessionManager()
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        sessions.transition(run.run_id, WorkflowState.REJECTED)

        coordinator = RecoveryCoordinator(session_manager=sessions)
        plan = coordinator.plan(run.run_id)
        self.assertEqual(plan.action, RecoveryAction.TERMINAL)
        self.assertFalse(plan.resumable)
        with self.assertRaises(RecoveryCoordinatorError):
            coordinator.apply(run_id=run.run_id, action=RecoveryAction.TERMINAL)


if __name__ == "__main__":
    unittest.main()
