import unittest

from app.core.contracts import ArtifactRef, HumanDecision, HumanDecisionType
from app.core.states import WorkflowState
from app.session.manager import SessionManager
from app.session.models import WorkerOutput
from app.session.repository import SessionNotFoundError


class SessionManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = SessionManager()

    def test_create_sessions_have_unique_ids_and_isolated_state(self):
        first = self.manager.create_session()
        second = self.manager.create_session()
        self.assertNotEqual(first.run_id, second.run_id)

        self.manager.add_message(first.run_id, role="user", content="first")
        self.assertEqual(len(self.manager.snapshot(first.run_id).messages), 1)
        self.assertEqual(len(self.manager.snapshot(second.run_id).messages), 0)

    def test_transition_delegates_to_core_state_machine(self):
        context = self.manager.create_session()
        self.manager.transition(context.run_id, WorkflowState.INTAKE)
        self.assertEqual(self.manager.get_context(context.run_id).state, WorkflowState.INTAKE)

        with self.assertRaises(Exception):
            self.manager.transition(context.run_id, WorkflowState.COMPLETED)

    def test_records_are_scoped_to_run(self):
        context = self.manager.create_session()
        artifact = ArtifactRef("a1", "report.txt", "text/plain")
        decision = HumanDecision(
            gate_id="gate-a",
            run_id=context.run_id,
            decision=HumanDecisionType.APPROVE,
            feedback="approved",
            timestamp="2026-09-08T00:00:00+00:00",
        )
        self.manager.add_artifact(context.run_id, artifact)
        self.manager.add_decision(context.run_id, decision)
        self.manager.set_worker_output(
            context.run_id,
            WorkerOutput("worker-1", context.run_id, "completed", {"ok": True}),
        )
        snapshot = self.manager.snapshot(context.run_id)
        self.assertEqual(len(snapshot.artifacts), 1)
        self.assertEqual(len(snapshot.decisions), 1)
        self.assertIn("worker-1", snapshot.worker_outputs)

    def test_cross_run_decision_is_rejected(self):
        first = self.manager.create_session()
        second = self.manager.create_session()
        decision = HumanDecision(
            gate_id="gate-a",
            run_id=first.run_id,
            decision=HumanDecisionType.APPROVE,
            feedback="approved",
            timestamp="2026-09-08T00:00:00+00:00",
        )
        with self.assertRaises(ValueError):
            self.manager.add_decision(second.run_id, decision)

    def test_destroy_removes_session(self):
        context = self.manager.create_session()
        self.manager.destroy_session(context.run_id)
        with self.assertRaises(SessionNotFoundError):
            self.manager.get_context(context.run_id)

    def test_empty_message_is_rejected(self):
        context = self.manager.create_session()
        with self.assertRaises(ValueError):
            self.manager.add_message(context.run_id, role="user", content="   ")


if __name__ == "__main__":
    unittest.main()
