import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.execution.lease import ExecutionLeaseService
from app.execution.reconciliation import ExecutionReconciliationService, ReconciliationStatus
from app.session.manager import SessionManager


class M38ReconciliationTests(unittest.TestCase):
    def test_completed_result_is_reconciled_from_persisted_evidence(self):
        sessions = SessionManager()
        run = sessions.create_session()
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
        sessions.add_execution_result(
            run.run_id,
            ExecutionResult(
                execution_id=lease.execution_id,
                status=ExecutionStatus.SUCCESS,
                exit_code=0,
                stdout="ok",
                stderr="",
                duration_ms=10,
                backend="fake",
            ),
        )
        result = ExecutionReconciliationService(session_manager=sessions).inspect(
            run_id=run.run_id,
            idempotency_key=key,
        )
        self.assertEqual(result.status, ReconciliationStatus.COMPLETED)

    def test_active_lease_without_result_requires_backend_check(self):
        sessions = SessionManager()
        run = sessions.create_session()
        service = ExecutionLeaseService(session_manager=sessions)
        key = service.idempotency_key(
            run_id=run.run_id,
            worker_id="worker-1",
            task_id="task-1",
            language="python",
            code="print('ok')",
        )
        service.reserve(
            run_id=run.run_id,
            worker_id="worker-1",
            task_id="task-1",
            idempotency_key=key,
            execution_id="exec-1",
        )
        result = ExecutionReconciliationService(session_manager=sessions).inspect(
            run_id=run.run_id,
            idempotency_key=key,
        )
        self.assertEqual(result.status, ReconciliationStatus.PENDING_BACKEND_CHECK)

    def test_missing_lease_does_not_permit_replay(self):
        sessions = SessionManager()
        run = sessions.create_session()
        result = ExecutionReconciliationService(session_manager=sessions).inspect(
            run_id=run.run_id,
            idempotency_key="missing",
        )
        self.assertEqual(result.status, ReconciliationStatus.NO_LEASE)


if __name__ == "__main__":
    unittest.main()
