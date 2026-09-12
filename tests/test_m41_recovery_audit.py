import tempfile
import unittest
from pathlib import Path

from app.core.states import WorkflowState
from app.execution.lease import ExecutionLeaseService
from app.execution.reconciliation import ExecutionReconciler, ExecutionReconciliationService, ReconciliationStatus
from app.recovery.models import RecoveryAction
from app.recovery.resume import RecoveryResumeService
from app.session.manager import SessionManager
from app.session.repository import SQLiteSessionRepository
from app.core.contracts import ExecutionResult, ExecutionStatus


class FakeReconciler(ExecutionReconciler):
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def reconcile(self, *, execution_id: str, idempotency_key: str) -> ExecutionResult | None:
        self.calls += 1
        return self.result


class M41RecoveryAuditTests(unittest.TestCase):
    def test_waiting_action_is_durably_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "sessions.db")
            first = SessionManager(SQLiteSessionRepository(database))
            run = first.create_session()
            first.transition(run.run_id, WorkflowState.INTAKE)
            first.transition(run.run_id, WorkflowState.ARCHITECTING)
            first.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)

            result = RecoveryResumeService(session_manager=first).resume(
                run_id=run.run_id,
                action=RecoveryAction.AWAIT_ARCHITECT_APPROVAL,
            )
            self.assertTrue(result.audit_event_id)

            second = SessionManager(SQLiteSessionRepository(database))
            record = second.snapshot(run.run_id)
            audit = [message for message in record.messages if message.metadata.get("phase") == "recovery_resume"]
            self.assertEqual(len(audit), 1)
            self.assertEqual(audit[0].metadata["event_id"], result.audit_event_id)
            self.assertEqual(audit[0].metadata["action"], RecoveryAction.AWAIT_ARCHITECT_APPROVAL.value)
            self.assertEqual(audit[0].metadata["previous_state"], WorkflowState.WAITING_ARCHITECT_APPROVAL.value)
            self.assertEqual(audit[0].metadata["resulting_state"], WorkflowState.WAITING_ARCHITECT_APPROVAL.value)
            self.assertEqual(record.context.state, WorkflowState.WAITING_ARCHITECT_APPROVAL)

    def test_execution_recovery_audit_contains_reconciliation_evidence(self):
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
                duration_ms=5,
                backend="colab",
            )
        )
        service = ExecutionReconciliationService(
            session_manager=sessions,
            backend_reconciler=reconciler,
        )
        result = RecoveryResumeService(
            session_manager=sessions,
            reconciliation_service=service,
        ).resume(
            run_id=run.run_id,
            action=RecoveryAction.RECONCILE_EXECUTION,
            idempotency_key=key,
        )

        self.assertEqual(result.reconciliation.status, ReconciliationStatus.COMPLETED)
        self.assertEqual(result.resulting_state, WorkflowState.SUPERVISING)
        audit = [message for message in sessions.snapshot(run.run_id).messages if message.metadata.get("phase") == "recovery_resume"]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0].metadata["reconciliation_status"], ReconciliationStatus.COMPLETED.value)
        self.assertEqual(audit[0].metadata["execution_id"], lease.execution_id)


if __name__ == "__main__":
    unittest.main()
