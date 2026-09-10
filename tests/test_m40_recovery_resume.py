import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.core.states import WorkflowState
from app.execution.lease import ExecutionLeaseService
from app.execution.reconciliation import ExecutionReconciler, ExecutionReconciliationService, ReconciliationStatus
from app.recovery.models import RecoveryAction
from app.recovery.resume import RecoveryResumeError, RecoveryResumeService
from app.session.manager import SessionManager


class FakeReconciler(ExecutionReconciler):
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def reconcile(self, *, execution_id: str, idempotency_key: str) -> ExecutionResult | None:
        self.calls += 1
        return self.result


class M40RecoveryResumeTests(unittest.TestCase):
    def test_revision_is_explicitly_reopened_for_architecture(self):
        sessions = SessionManager()
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        sessions.transition(run.run_id, WorkflowState.REVISION)

        result = RecoveryResumeService(session_manager=sessions).resume(
            run_id=run.run_id,
            action=RecoveryAction.REBUILD_ARCHITECTURE,
        )
        self.assertEqual(result.resulting_state, WorkflowState.ARCHITECTING)

    def test_action_mismatch_is_rejected_without_state_change(self):
        sessions = SessionManager()
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)

        service = RecoveryResumeService(session_manager=sessions)
        with self.assertRaises(RecoveryResumeError):
            service.resume(
                run_id=run.run_id,
                action=RecoveryAction.RESUME_SUPERVISION,
            )
        self.assertEqual(sessions.get_context(run.run_id).state, WorkflowState.ARCHITECTING)

    def test_execution_reconciliation_persists_authoritative_success_and_resumes_supervision(self):
        sessions = SessionManager()
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        sessions.transition(run.run_id, WorkflowState.EXECUTING)

        lease_service = ExecutionLeaseService(session_manager=sessions)
        key = lease_service.idempotency_key(
            run_id=run.run_id,
            worker_id="worker-1",
            task_id="task-1",
            language="python",
            code="print('ok')",
        )
        lease = lease_service.reserve(
            run_id=run.run_id,
            worker_id="worker-1",
            task_id="task-1",
            idempotency_key=key,
            execution_id="exec-1",
        )
        reconciler = FakeReconciler(
            ExecutionResult(
                execution_id=lease.execution_id,
                status=ExecutionStatus.SUCCESS,
                exit_code=0,
                stdout="ok",
                stderr="",
                duration_ms=11,
                backend="fake",
            )
        )
        reconciliation = ExecutionReconciliationService(
            session_manager=sessions,
            backend_reconciler=reconciler,
        )
        result = RecoveryResumeService(
            session_manager=sessions,
            reconciliation_service=reconciliation,
        ).resume(
            run_id=run.run_id,
            action=RecoveryAction.RECONCILE_EXECUTION,
            idempotency_key=key,
        )

        self.assertEqual(result.reconciliation.status, ReconciliationStatus.COMPLETED)
        self.assertEqual(result.resulting_state, WorkflowState.SUPERVISING)
        self.assertEqual(reconciler.calls, 1)
        self.assertEqual(len(sessions.snapshot(run.run_id).execution_results), 1)

    def test_execution_without_idempotency_key_is_rejected(self):
        sessions = SessionManager()
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        sessions.transition(run.run_id, WorkflowState.EXECUTING)

        with self.assertRaises(RecoveryResumeError):
            RecoveryResumeService(session_manager=sessions).resume(
                run_id=run.run_id,
                action=RecoveryAction.RECONCILE_EXECUTION,
            )


if __name__ == "__main__":
    unittest.main()
