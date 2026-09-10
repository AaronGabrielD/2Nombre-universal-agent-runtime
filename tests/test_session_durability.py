import tempfile
import unittest
from pathlib import Path

from app.core.contracts import ArtifactRef, FinalResult, HumanDecision, HumanDecisionType
from app.core.states import TERMINAL_STATES, WorkflowState
from app.session.json_repository import JsonFileSessionRepository
from app.session.manager import SessionManager
from app.session.repository import InMemorySessionRepository, SessionNotFoundError, SQLiteSessionRepository


class SessionRepositoryDurabilityTests(unittest.TestCase):
    def exercise_repository(self, repository):
        manager = SessionManager(repository)
        first = manager.create_session(metadata={"owner_id": "user-a"})
        second = manager.create_session(metadata={"owner_id": "user-b"})

        manager.add_message(first.run_id, role="user", content="first")
        manager.add_artifact(first.run_id, ArtifactRef("artifact-1", "result.txt", "text/plain"))
        manager.add_decision(first.run_id, HumanDecision(
            gate_id="gate-a", run_id=first.run_id, decision=HumanDecisionType.APPROVE,
            feedback="approved", timestamp="2026-09-10T00:00:00+00:00"))
        manager.set_final_result(first.run_id, FinalResult(run_id=first.run_id, status="ready", summary="done"))
        manager.transition(first.run_id, WorkflowState.INTAKE)

        first_snapshot = manager.snapshot(first.run_id)
        second_snapshot = manager.snapshot(second.run_id)
        self.assertEqual(first_snapshot.context.metadata["owner_id"], "user-a")
        self.assertEqual(len(first_snapshot.messages), 1)
        self.assertEqual(len(first_snapshot.artifacts), 1)
        self.assertEqual(len(first_snapshot.decisions), 1)
        self.assertEqual(first_snapshot.final_result.run_id, first.run_id)
        self.assertEqual(second_snapshot.messages, [])
        self.assertEqual(second_snapshot.artifacts, [])
        self.assertEqual(second_snapshot.decisions, [])
        self.assertIsNone(second_snapshot.final_result)

        first_snapshot.context.metadata["owner_id"] = "mutated"
        self.assertEqual(manager.get_context(first.run_id).metadata["owner_id"], "user-a")

    def test_in_memory_repository_isolated(self):
        self.exercise_repository(InMemorySessionRepository())

    def test_sqlite_repository_survives_manager_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "sessions.db")
            manager = SessionManager(SQLiteSessionRepository(database_path))
            run = manager.create_session(metadata={"owner_id": "user-a"})
            manager.add_message(run.run_id, role="user", content="persist me")
            manager.transition(run.run_id, WorkflowState.INTAKE)
            restarted = SessionManager(SQLiteSessionRepository(database_path))
            restored = restarted.snapshot(run.run_id)
            self.assertEqual(restored.context.run_id, run.run_id)
            self.assertEqual(restored.context.state, WorkflowState.INTAKE)
            self.assertEqual(restored.messages[0].content, "persist me")

    def test_json_repository_survives_manager_restart_and_rejects_unsafe_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = str(Path(directory) / "sessions")
            manager = SessionManager(JsonFileSessionRepository(root))
            run = manager.create_session(metadata={"owner_id": "user-a"})
            manager.add_message(run.run_id, role="user", content="persist me")
            restarted = SessionManager(JsonFileSessionRepository(root))
            restored = restarted.snapshot(run.run_id)
            self.assertEqual(restored.context.run_id, run.run_id)
            self.assertEqual(restored.messages[0].content, "persist me")
            with self.assertRaises(ValueError):
                restarted.get_context("../escape")

    def test_recoverable_session_listing_excludes_terminal_runs(self):
        manager = SessionManager()
        active = manager.create_session()
        terminal = manager.create_session()
        manager.transition(terminal.run_id, WorkflowState.INTAKE)
        manager.transition(terminal.run_id, WorkflowState.ARCHITECTING)
        manager.transition(terminal.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        manager.transition(terminal.run_id, WorkflowState.REJECTED)
        recoverable = manager.list_recoverable_sessions()
        recoverable_ids = {record.context.run_id for record in recoverable}
        self.assertIn(active.run_id, recoverable_ids)
        self.assertNotIn(terminal.run_id, recoverable_ids)
        self.assertEqual(TERMINAL_STATES & {record.context.state for record in recoverable}, set())

    def test_missing_session_operations_fail_closed(self):
        manager = SessionManager()
        with self.assertRaises(SessionNotFoundError):
            manager.get_context("missing-run")
        with self.assertRaises(SessionNotFoundError):
            manager.add_message("missing-run", role="user", content="x")


if __name__ == "__main__":
    unittest.main()
