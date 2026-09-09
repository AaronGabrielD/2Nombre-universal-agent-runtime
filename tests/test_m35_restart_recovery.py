import tempfile
import unittest
from pathlib import Path

from app.core.states import WorkflowState
from app.session.json_repository import JsonFileSessionRepository
from app.session.manager import SessionManager
from app.session.repository import SQLiteSessionRepository


class M35RestartRecoveryTests(unittest.TestCase):
    def _make_active_run(self, sessions: SessionManager):
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.add_message(
            run.run_id,
            role="user",
            content="resume me",
            metadata={"phase": "intake"},
        )
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        return run

    def _make_terminal_run(self, sessions: SessionManager):
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        sessions.transition(run.run_id, WorkflowState.REJECTED)
        return run

    def test_in_memory_inventory_and_recoverable_filter(self):
        sessions = SessionManager()
        active = self._make_active_run(sessions)
        terminal = self._make_terminal_run(sessions)

        all_runs = sessions.list_sessions()
        recoverable = sessions.list_recoverable_sessions()

        self.assertEqual([record.context.run_id for record in all_runs], sorted([active.run_id, terminal.run_id]))
        self.assertEqual([record.context.run_id for record in recoverable], [active.run_id])
        recoverable[0].context.metadata["mutated"] = "outside"
        self.assertNotIn("mutated", sessions.get_context(active.run_id).metadata)

    def test_json_repository_discovers_sessions_after_manager_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            first = SessionManager(JsonFileSessionRepository(directory))
            active = self._make_active_run(first)
            self._make_terminal_run(first)

            second = SessionManager(JsonFileSessionRepository(directory))
            recoverable = second.list_recoverable_sessions()

            self.assertEqual(len(recoverable), 1)
            self.assertEqual(recoverable[0].context.run_id, active.run_id)
            self.assertEqual(recoverable[0].context.state, WorkflowState.ARCHITECTING)
            self.assertEqual(recoverable[0].messages[-1].content, "resume me")

    def test_sqlite_repository_discovers_sessions_after_manager_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "sessions.db")
            first = SessionManager(SQLiteSessionRepository(database))
            active = self._make_active_run(first)
            self._make_terminal_run(first)

            second = SessionManager(SQLiteSessionRepository(database))
            recoverable = second.list_recoverable_sessions()

            self.assertEqual(len(recoverable), 1)
            self.assertEqual(recoverable[0].context.run_id, active.run_id)
            self.assertEqual(recoverable[0].context.state, WorkflowState.ARCHITECTING)

    def test_recovery_inventory_does_not_execute_or_change_state(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions = SessionManager(JsonFileSessionRepository(directory))
            active = self._make_active_run(sessions)

            recovered = sessions.list_recoverable_sessions()

            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0].context.state, WorkflowState.ARCHITECTING)
            self.assertEqual(sessions.get_context(active.run_id).state, WorkflowState.ARCHITECTING)
            self.assertEqual(sessions.list_recoverable_sessions()[0].context.state, WorkflowState.ARCHITECTING)


if __name__ == "__main__":
    unittest.main()
