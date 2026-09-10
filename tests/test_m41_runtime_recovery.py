import unittest

from app.core.states import WorkflowState
from app.recovery.models import RecoveryAction
from app.runtime.service import RuntimeCoordinator


class M41RuntimeRecoveryTests(unittest.TestCase):
    def test_coordinator_exposes_recovery_checkpoint(self):
        coordinator = RuntimeCoordinator()
        run = coordinator.start_run("recover me")
        checkpoint = coordinator.inspect_recovery(run.run_id)
        self.assertEqual(checkpoint.state, WorkflowState.INTAKE)
        self.assertFalse(checkpoint.safe_to_automatically_execute)

    def test_coordinator_lists_recovery_checkpoints_deterministically(self):
        coordinator = RuntimeCoordinator()
        first = coordinator.start_run("first")
        second = coordinator.start_run("second")
        checkpoints = coordinator.list_recovery_checkpoints()
        self.assertEqual([item.run_id for item in checkpoints], sorted([first.run_id, second.run_id]))

    def test_coordinator_rejects_ambiguous_recovery_action_without_mutation(self):
        coordinator = RuntimeCoordinator()
        run = coordinator.start_run("recover me")
        with self.assertRaises(ValueError):
            coordinator.resume_recovery(
                run_id=run.run_id,
                action=RecoveryAction.RESUME_SUPERVISION,
            )
        self.assertEqual(coordinator.sessions.get_context(run.run_id).state, WorkflowState.INTAKE)

    def test_coordinator_can_explicitly_reopen_revision(self):
        coordinator = RuntimeCoordinator()
        run = coordinator.start_run("recover revision")
        coordinator.sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        coordinator.sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        coordinator.sessions.transition(run.run_id, WorkflowState.EXECUTING)
        coordinator.sessions.transition(run.run_id, WorkflowState.SUPERVISING)
        coordinator.record_revision(
            run.run_id,
            reason="test recovery",
            source="test",
            feedback="rebuild",
        )
        result = coordinator.resume_recovery(
            run_id=run.run_id,
            action=RecoveryAction.REBUILD_ARCHITECTURE,
        )
        self.assertEqual(result.resulting_state, WorkflowState.ARCHITECTING)


if __name__ == "__main__":
    unittest.main()
