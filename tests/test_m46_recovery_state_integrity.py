import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.core.states import WorkflowState
from app.execution.lease import ExecutionLeaseService
from app.execution.reconciliation import (
    ExecutionReconciler,
    ExecutionReconciliationService,
    ReconciliationStatus,
)
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


class M46RecoveryStateIntegrityTests(unittest.TestCase):
    def test_failed_execution_uses_legal_revision_path_and_preserves_audit(self):
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
            worker_id="worker-m46",
            task_id="task-m46",
            language="python",
            code="raise RuntimeError('boom')",
        )
        lease = leases.reserve(
            run_id=run.run_id,
            worker_id="worker-m46",
            task_id="task-m46",
            idempotency_key=key,
            execution_id="exec-m46",
        )
        failure = ExecutionResult(
            execution_id=lease.execution_id,
            status=ExecutionStatus.ERROR,
            exit_code=1,
            stdout="",
            stderr="boom",
            duration_ms=9,
            backend="colab",
        )
        reconciler = FailedExecutionReconciler(failure)
        reconciliation = ExecutionReconciliationService(
            session_manager=sessions,
            backend_reconciler=reconciler,
        )
        revisions = RevisionService(session_manager=sessions)
        service = RecoveryResumeService(
            session_manager=sessions,
            reconciliation_service=reconciliation,
            revision_service=revisions,
        )

        result = service.resume(
            run_id=run.run_id,
            action=RecoveryAction.RECONCILE_EXECUTION,
            idempotency_key=key,
        )

        self.assertEqual(result.reconciliation.status, ReconciliationStatus.FAILED)
        self.assertEqual(result.resulting_state, WorkflowState.ARCHITECTING)
        self.assertEqual(sessions.get_context(run.run_id).state, WorkflowState.ARCHITECTING)
        self.assertEqual(reconciler.calls, 1)
        revision_history = revisions.list_revisions(run.run_id)
        self.assertEqual(len(revision_history), 1)
        self.assertEqual(revision_history[0].source, "recovery")
        self.assertEqual(revision_history[0].feedback, "boom")

        audit_events = [
            message
            for message in sessions.snapshot(run.run_id).messages
            if message.metadata.get("phase") == RecoveryResumeService.AUDIT_PHASE
        ]
        self.assertEqual(len(audit_events), 1)
        self.assertEqual(audit_events[0].metadata["previous_state"], WorkflowState.EXECUTING.value)
        self.assertEqual(audit_events[0].metadata["resulting_state"], WorkflowState.ARCHITECTING.value)
        self.assertEqual(audit_events[0].metadata["reconciliation_status"], ReconciliationStatus.FAILED.value)
        self.assertEqual(audit_events[0].metadata["execution_id"], lease.execution_id)
        self.assertEqual(audit_events[0].metadata["revision_id"], revision_history[0].revision_id)


if __name__ == "__main__":
    unittest.main()
