import tempfile
import unittest
from pathlib import Path

from app.core.states import WorkflowState
from app.recovery.models import RecoveryAction
from app.recovery.service import RecoveryService, RecoveryServiceError
from app.session.json_repository import JsonFileSessionRepository
from app.session.manager import SessionManager


class M36RecoveryTests(unittest.TestCase):
    def _run_in_state(self, sessions: SessionManager, state: WorkflowState):
        run = sessions.create_session()
        path = {
            WorkflowState.ARCHITECTING: [WorkflowState.INTAKE, WorkflowState.ARCHITECTING],
            WorkflowState.WAITING_ARCHITECT_APPROVAL: [WorkflowState.INTAKE, WorkflowState.ARCHITECTING, WorkflowState.WAITING_ARCHITECT_APPROVAL],
            WorkflowState.EXECUTING: [WorkflowState.INTAKE, WorkflowState.ARCHITECTING, WorkflowState.WAITING_ARCHITECT_APPROVAL, WorkflowState.EXECUTING],
            WorkflowState.WORKER_WAITING_HUMAN: [WorkflowState.INTAKE, WorkflowState.ARCHITECTING, WorkflowState.WAITING_ARCHITECT_APPROVAL, WorkflowState.EXECUTING, WorkflowState.WORKER_WAITING_HUMAN],
            WorkflowState.SUPERVISING: [WorkflowState.INTAKE, WorkflowState.ARCHITECTING, WorkflowState.WAITING_ARCHITECT_APPROVAL, WorkflowState.EXECUTING, WorkflowState.SUPERVISING],
            WorkflowState.WAITING_FINAL_APPROVAL: [WorkflowState.INTAKE, WorkflowState.ARCHITECTING, WorkflowState.WAITING_ARCHITECT_APPROVAL, WorkflowState.EXECUTING, WorkflowState.SUPERVISING, WorkflowState.WAITING_FINAL_APPROVAL],
            WorkflowState.REVISION: [WorkflowState.INTAKE, WorkflowState.ARCHITECTING, WorkflowState.WAITING_ARCHITECT_APPROVAL, WorkflowState.EXECUTING, WorkflowState.SUPERVISING, WorkflowState.REVISION],
            WorkflowState.REJECTED: [WorkflowState.INTAKE, WorkflowState.ARCHITECTING, WorkflowState.WAITING_ARCHITECT_APPROVAL, WorkflowState.REJECTED],
        }[state]
        for step in path:
            sessions.transition(run.run_id, step)
        return run

    def test_classifies_execution_as_reconciliation_not_replay(self):
        sessions = SessionManager()
        run = self._run_in_state(sessions, WorkflowState.EXECUTING)
        service = RecoveryService(session_manager=sessions)
        checkpoint = service.inspect(run.run_id)
        self.assertEqual(checkpoint.action, RecoveryAction.RECONCILE_EXECUTION)
        self.assertFalse(checkpoint.safe_to_automatically_execute)
        self.assertEqual(sessions.get_context(run.run_id).state, WorkflowState.EXECUTING)

    def test_classifies_waiting_states_without_mutation(self):
        sessions = SessionManager()
        expected = {
            WorkflowState.ARCHITECTING: RecoveryAction.REBUILD_ARCHITECTURE,
            WorkflowState.WAITING_ARCHITECT_APPROVAL: RecoveryAction.AWAIT_ARCHITECT_APPROVAL,
            WorkflowState.WORKER_WAITING_HUMAN: RecoveryAction.AWAIT_HUMAN_GATE,
            WorkflowState.SUPERVISING: RecoveryAction.RESUME_SUPERVISION,
            WorkflowState.WAITING_FINAL_APPROVAL: RecoveryAction.AWAIT_FINAL_APPROVAL,
            WorkflowState.REVISION: RecoveryAction.REBUILD_ARCHITECTURE,
            WorkflowState.REJECTED: RecoveryAction.TERMINAL,
        }
        for state, action in expected.items():
            run = self._run_in_state(sessions, state)
            checkpoint = RecoveryService(session_manager=sessions).inspect(run.run_id)
            self.assertEqual(checkpoint.action, action)
            self.assertFalse(checkpoint.safe_to_automatically_execute)
            self.assertEqual(sessions.get_context(run.run_id).state, state)

    def test_inventory_is_deterministic_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            first = SessionManager(JsonFileSessionRepository(directory))
            a = self._run_in_state(first, WorkflowState.ARCHITECTING)
            b = self._run_in_state(first, WorkflowState.EXECUTING)
            second = SessionManager(JsonFileSessionRepository(directory))
            checkpoints = RecoveryService(session_manager=second).list_checkpoints()
            self.assertEqual([item.run_id for item in checkpoints], sorted([a.run_id, b.run_id]))
            self.assertEqual(checkpoints[0].execution_result_count, 0)

    def test_unknown_run_is_rejected(self):
        service = RecoveryService(session_manager=SessionManager())
        with self.assertRaises(RecoveryServiceError):
            service.inspect("missing-run")


if __name__ == "__main__":
    unittest.main()
