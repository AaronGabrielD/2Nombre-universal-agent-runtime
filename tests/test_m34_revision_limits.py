import unittest

from app.core.states import WorkflowState
from app.revision.service import RevisionService, RevisionServiceError
from app.session.manager import SessionManager


class M34RevisionLimitTests(unittest.TestCase):
    def setUp(self):
        self.sessions = SessionManager()
        self.run = self.sessions.create_session()
        self.service = RevisionService(session_manager=self.sessions, max_revisions=2)

    def _enter_revision(self):
        run_id = self.run.run_id
        self.sessions.transition(run_id, WorkflowState.INTAKE)
        self.sessions.transition(run_id, WorkflowState.ARCHITECTING)
        self.sessions.transition(run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        self.sessions.transition(run_id, WorkflowState.EXECUTING)
        self.sessions.transition(run_id, WorkflowState.SUPERVISING)
        self.sessions.transition(run_id, WorkflowState.REVISION)

    def _complete_revision_cycle_to_revision(self):
        run_id = self.run.run_id
        self.sessions.transition(run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        self.sessions.transition(run_id, WorkflowState.EXECUTING)
        self.sessions.transition(run_id, WorkflowState.SUPERVISING)
        self.sessions.transition(run_id, WorkflowState.REVISION)

    def test_limit_blocks_next_revision_without_state_change(self):
        self._enter_revision()
        self.service.request_revision(self.run.run_id, reason="first", source="qa")
        self._complete_revision_cycle_to_revision()
        self.service.request_revision(self.run.run_id, reason="second", source="qa")
        self._complete_revision_cycle_to_revision()

        with self.assertRaises(RevisionServiceError) as ctx:
            self.service.request_revision(self.run.run_id, reason="third", source="qa")

        self.assertIn("revision limit reached (2)", str(ctx.exception))
        self.assertEqual(self.sessions.get_context(self.run.run_id).state, WorkflowState.REVISION)
        self.assertEqual(len(self.service.list_revisions(self.run.run_id)), 2)

    def test_limit_is_revalidated_after_service_reopen(self):
        self._enter_revision()
        self.service.request_revision(self.run.run_id, reason="first", source="qa")
        self._complete_revision_cycle_to_revision()
        self.service.request_revision(self.run.run_id, reason="second", source="qa")
        self._complete_revision_cycle_to_revision()

        reopened = RevisionService(session_manager=self.sessions, max_revisions=2)
        with self.assertRaises(RevisionServiceError):
            reopened.request_revision(self.run.run_id, reason="third", source="qa")
        self.assertEqual(len(reopened.list_revisions(self.run.run_id)), 2)

    def test_max_revisions_requires_positive_integer(self):
        with self.assertRaises(RevisionServiceError):
            RevisionService(session_manager=self.sessions, max_revisions=0)
        with self.assertRaises(RevisionServiceError):
            RevisionService(session_manager=self.sessions, max_revisions=True)


if __name__ == "__main__":
    unittest.main()
