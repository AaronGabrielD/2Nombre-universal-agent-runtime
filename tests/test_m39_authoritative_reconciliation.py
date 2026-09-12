import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.execution.reconciliation import (
    ExecutionReconciler,
    ExecutionReconciliationService,
    ReconciliationStatus,
)
from app.execution.lease import ExecutionLeaseService
from app.session.manager import SessionManager


class FakeReconciler(ExecutionReconciler):
    def __init__(self, result):
        self.result = result
        self.calls = []

    def reconcile(self, *, execution_id: str, idempotency_key: str):
        self.calls.append((execution_id, idempotency_key))
        return self.result


def make_pending_run():
    sessions = SessionManager()
    run = sessions.create_session()
    leases = ExecutionLeaseService(session_manager=sessions)
    key = leases.idempotency_key(
        run_id=run.run_id,
        worker_id="worker-1",
        task_id="task-1",
        language="python",
        code="print('ok')",
    )
    lease = leases.reserve(
        run_id=run.run_id,
        worker_id="worker-1",
        task_id="task-1",
        idempotency_key=key,
        execution_id="exec-1",
    )
    return sessions, run, key, lease


class M39AuthoritativeReconciliationTests(unittest.TestCase):
    def test_no_backend_capability_fails_closed(self):
        sessions, run, key, lease = make_pending_run()
        result = ExecutionReconciliationService(session_manager=sessions).reconcile_backend(
            run_id=run.run_id, idempotency_key=key
        )
        self.assertEqual(result.status, ReconciliationStatus.BACKEND_UNAVAILABLE)
        self.assertEqual(result.execution_id, lease.execution_id)

    def test_backend_no_result_does_not_permit_retry(self):
        sessions, run, key, _ = make_pending_run()
        backend = FakeReconciler(None)
        result = ExecutionReconciliationService(
            session_manager=sessions, backend_reconciler=backend
        ).reconcile_backend(run_id=run.run_id, idempotency_key=key)
        self.assertEqual(result.status, ReconciliationStatus.BACKEND_NO_RESULT)
        self.assertEqual(len(sessions.snapshot(run.run_id).execution_results), 0)
        self.assertEqual(len(backend.calls), 1)

    def test_authoritative_result_is_persisted(self):
        sessions, run, key, lease = make_pending_run()
        authoritative = ExecutionResult(
            execution_id=lease.execution_id,
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="remote-ok",
            stderr="",
            duration_ms=12,
            backend="colab",
        )
        backend = FakeReconciler(authoritative)
        service = ExecutionReconciliationService(
            session_manager=sessions, backend_reconciler=backend
        )
        first = service.reconcile_backend(run_id=run.run_id, idempotency_key=key)
        self.assertEqual(first.status, ReconciliationStatus.COMPLETED)
        persisted = sessions.snapshot(run.run_id).execution_results
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].execution_id, lease.execution_id)

        second = service.inspect(run_id=run.run_id, idempotency_key=key)
        self.assertEqual(second.status, ReconciliationStatus.COMPLETED)
        self.assertEqual(len(backend.calls), 1)

    def test_inconsistent_backend_execution_id_is_rejected_and_not_persisted(self):
        sessions, run, key, _ = make_pending_run()
        backend = FakeReconciler(
            ExecutionResult(
                execution_id="wrong-id",
                status=ExecutionStatus.SUCCESS,
                exit_code=0,
                stdout="",
                stderr="",
                duration_ms=1,
                backend="colab",
            )
        )
        service = ExecutionReconciliationService(
            session_manager=sessions, backend_reconciler=backend
        )
        with self.assertRaises(ValueError):
            service.reconcile_backend(run_id=run.run_id, idempotency_key=key)
        self.assertEqual(len(sessions.snapshot(run.run_id).execution_results), 0)

    def test_existing_local_evidence_is_authoritative_and_skips_backend(self):
        sessions, run, key, lease = make_pending_run()
        sessions.add_execution_result(
            run.run_id,
            ExecutionResult(
                execution_id=lease.execution_id,
                status=ExecutionStatus.ERROR,
                exit_code=2,
                stdout="",
                stderr="boom",
                duration_ms=5,
                backend="local-fake",
            ),
        )
        backend = FakeReconciler(None)
        result = ExecutionReconciliationService(
            session_manager=sessions, backend_reconciler=backend
        ).reconcile_backend(run_id=run.run_id, idempotency_key=key)
        self.assertEqual(result.status, ReconciliationStatus.FAILED)
        self.assertEqual(len(backend.calls), 0)


if __name__ == "__main__":
    unittest.main()
