import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.core.states import WorkflowState
from app.execution.lease import ExecutionLeaseService
from app.execution.reconciliation import ExecutionReconciler, ExecutionReconciliationService, ReconciliationStatus
from app.recovery.models import RecoveryAction
from app.recovery.resume import RecoveryResumeService
from app.revision.service import RevisionService
from app.session.manager import SessionManager


class FailedExecutionReconciler(ExecutionReconciler):
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result
        self.calls = 0

    def reconcile(self, *, execution_id: str, idempotency_key: str) -> ExecutionResult | None:
        self.calls += 1
        return self.result


class M42RecoveryFailureRoutingTests(unittest.TestCase):
    def test_failed_recovery_routes_through_supervision_and_revision_service(self):
        sessions = SessionManager()
        run = sessions.create_session()
        for state in (
            WorkflowState.INTAKE,
            WorkflowState.ARCHITECTING,
            WorkflowState.WAITING_ARCHITECT_APPROVAL,
            WorkflowState.EXECUTING,
        ):
            sessions.transition(run.run_id, state)

        leases = ExecutionLeaseService(session_manager=sessions)
        key = leases.idempotency_key(
            run_id=run.run_id,
            worker_id="worker-42",
            task_id="task-42",
            language="python",
            code="raise RuntimeError('boom')",
        )
        lease = leases.reserve(
            run_id=run.run_id,
            worker_id="worker-42",
            task_id="task-42",
            idempotency_key=key,
            execution_id="exec-m42",
        )
        failure = ExecutionResult(
            execution_id=lease.execution_id,
            status=ExecutionStatus.ERROR,
            exit_code=1,
            stdout="",
            stderr="boom",
            duration_ms=9,
            backend="fake",
        )
        reconciler = FailedExecutionReconciler(failure)
        reconciliation = ExecutionReconciliationService(
            session_manager=sessions,
            backend_reconciler=reconciler,
        )
        revisions = RevisionService(session_manager=sessions)

        result = RecoveryResumeService(
            session_manager=sessions,
            reconciliation_service=reconciliation,
            revision_service=revisions,
        ).resume(
            run_id=run.run_id,
            action=RecoveryAction.RECONCILE_EXECUTION,
            idempotency_key=key,
        )

        self.assertEqual(result.reconciliation.status, ReconciliationStatus.FAILED)
        self.assertEqual(result.resulting_state, WorkflowState.ARCHITECTING)
        self.assertEqual(sessions.get_context(run.run_id).state, WorkflowState.ARCHITECTING)
        self.assertEqual(reconciler.calls, 1)
        self.assertEqual(len(sessions.snapshot(run.run_id).execution_results), 1)
        revision_history = revisions.list_revisions(run.run_id)
        self.assertEqual(len(revision_history), 1)
        self.assertEqual(revision_history[0].source, "recovery")


if __name__ == "__main__":
    unittest.main()
