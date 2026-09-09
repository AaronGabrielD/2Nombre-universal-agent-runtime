import os
import tempfile
import unittest

from app.core.contracts import ArchitecturePlan, WorkerSpec
from app.core.states import WorkflowState
from app.session.manager import SessionManager
from app.session.repository import SQLiteSessionRepository, SessionNotFoundError


class SQLiteSessionRepositoryTests(unittest.TestCase):
    def test_session_state_survives_repository_recreation(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = os.path.join(tmp, "runtime.db")
            manager = SessionManager(repository=SQLiteSessionRepository(database))
            run = manager.create_session(metadata={"source": "test"})
            manager.add_message(run.run_id, role="user", content="hello")
            manager.set_architecture_plan(
                run.run_id,
                ArchitecturePlan(
                    plan_id="plan-sqlite",
                    objective="persist state",
                    acceptance_criteria=("state survives reopen",),
                    workers=(WorkerSpec(worker_id="worker-1", role="builder", mission="build"),),
                ),
            )

            reopened = SessionManager(repository=SQLiteSessionRepository(database))
            snapshot = reopened.snapshot(run.run_id)
            self.assertEqual(snapshot.context.run_id, run.run_id)
            self.assertEqual(snapshot.context.metadata["source"], "test")
            self.assertEqual(snapshot.messages[0].content, "hello")
            self.assertEqual(snapshot.architecture_plan.plan_id, "plan-sqlite")

    def test_mutations_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = os.path.join(tmp, "runtime.db")
            manager = SessionManager(repository=SQLiteSessionRepository(database))
            run = manager.create_session()
            manager.transition(run.run_id, WorkflowState.INTAKE)
            manager.transition(run.run_id, WorkflowState.ARCHITECTING)

            reopened = SessionManager(repository=SQLiteSessionRepository(database))
            self.assertEqual(reopened.get_context(run.run_id).state, WorkflowState.ARCHITECTING)

    def test_missing_session_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = SQLiteSessionRepository(os.path.join(tmp, "runtime.db"))
            with self.assertRaises(SessionNotFoundError):
                repository.get("missing-run")


if __name__ == "__main__":
    unittest.main()
