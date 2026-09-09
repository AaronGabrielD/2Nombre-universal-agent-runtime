import unittest

from app.core.states import WorkflowState
from app.revision.models import RevisionRequest
from app.revision.service import RevisionService, RevisionServiceError
from app.session.manager import SessionManager


class M32RevisionTests(unittest.TestCase):
    def setUp(self):
        self.sessions = SessionManager()
        self.run = self.sessions.create_session()
        self.service = RevisionService(session_manager=self.sessions)

    def test_revision_from_revision_moves_to_architecting_and_tracks_attempt(self):
        self.sessions.transition(self.run.run_id, WorkflowState.INTAKE)
        self.sessions.transition(self.run.run_id, WorkflowState.ARCHITECTING)
        self.sessions.transition(self.run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        self.sessions.transition(self.run.run_id, WorkflowState.ARCHITECTING)
        self.sessions.transition(self.run.run_id, WorkflowState.REVISION)

        revision = self.service.request_revision(
            self.run.run_id,
            reason="QA found missing evidence",
            source="supervisor",
            feedback="Add executable evidence",
        )

        self.assertIsInstance(revision, RevisionRequest)
        self.assertEqual(revision.attempt, 1)
        self.assertEqual(
            self.sessions.get_context(self.run.run_id).state,
            WorkflowState.ARCHITECTING,
        )
        self.assertEqual(len(self.service.list_revisions(self.run.run_id)), 1)

    def test_empty_reason_is_rejected_without_state_change(self):
        self.sessions.transition(self.run.run_id, WorkflowState.INTAKE)
        self.sessions.transition(self.run.run_id, WorkflowState.ARCHITECTING)
        self.sessions.transition(self.run.run_id, WorkflowState.REVISION)

        with self.assertRaises(RevisionServiceError):
            self.service.request_revision(self.run.run_id, reason=" ")

        self.assertEqual(
            self.sessions.get_context(self.run.run_id).state,
            WorkflowState.REVISION,
        )
        self.assertEqual(self.service.list_revisions(self.run.run_id), ())

    def test_revision_history_is_defensive(self):
        self.sessions.transition(self.run.run_id, WorkflowState.INTAKE)
        self.sessions.transition(self.run.run_id, WorkflowState.ARCHITECTING)
        self.sessions.transition(self.run.run_id, WorkflowState.REVISION)
        first = self.service.request_revision(
            self.run.run_id,
            reason="retry",
            source="human",
        )
        history = self.service.list_revisions(self.run.run_id)
        self.assertEqual(history[0], first)
        self.assertIsNot(history[0], first)


if __name__ == "__main__":
    unittest.main()
