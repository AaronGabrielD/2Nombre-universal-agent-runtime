import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.core.states import WorkflowState
from app.execution import (
    ExecutionLeaseService,
    ExecutionReconciler,
    ExecutionReconciliationService,
    ReconciliationStatus,
    RunExecutionReconciliationService,
)
from app.session.manager import SessionManager


class FakeReconciler(ExecutionReconciler):
    def __init__(self, results):
        self.results = dict(results)
        self.calls = []

    def reconcile(self, *, execution_id: str, idempotency_key: str) -> ExecutionResult | None:
        self.calls.append((execution_id, idempotency_key))
        return self.results.get(execution_id)


class M46ReconciliationBatchTests(unittest.TestCase):
    def _session_with_leases(self):
        sessions = SessionManager()
        run = sessions.create_session()
        for state in (
            WorkflowState.INTAKE,
            WorkflowState.ARCHITECTING,
            WorkflowState.WAITING_ARCHITECT_APPROVAL,
            WorkflowState.EXECUTING,
        ):
            sessions.transition(run.run_id, state)
        service = ExecutionLeaseService(session_manager=sessions)

        leases = []
        for worker_id, task_id, execution_id in (
            ("worker-a", "task-a", "exec-a"),
            ("worker-b", "task-b", "exec-b"),
        ):
            key = service.idempotency_key(
                run_id=run.run_id,
                worker_id=worker_id,
                task_id=task_id,
                language="python",
                code=f"print('{execution_id}')",
            )
            leases.append(
                service.reserve(
                    run_id=run.run_id,
                    worker_id=worker_id,
                    task_id=task_id,
                    idempotency_key=key,
                    execution_id=execution_id,
                )
            )
        return sessions, run.run_id, leases

    def test_inspect_returns_latest_durable_leases_in_deterministic_order(self):
        sessions, run_id, leases = self._session_with_leases()
        sessions.add_execution_result(
            run_id,
            ExecutionResult(
                execution_id=leases[0].execution_id,
                status=ExecutionStatus.SUCCESS,
                exit_code=0,
                stdout="ok",
                stderr="",
                duration_ms=1,
                backend="fake",
            ),
        )

        result = RunExecutionReconciliationService(session_manager=sessions).inspect(run_id)
        self.assertEqual([item.task_id for item in result.items], ["task-a", "task-b"])
        self.assertEqual(result.items[0].status, ReconciliationStatus.COMPLETED)
        self.assertEqual(result.items[1].status, ReconciliationStatus.PENDING_BACKEND_CHECK)
        self.assertEqual(len(result.terminal), 1)
        self.assertEqual(len(result.pending), 1)

    def test_backend_reconciliation_only_calls_backend_for_pending_leases(self):
        sessions, run_id, leases = self._session_with_leases()
        sessions.add_execution_result(
            run_id,
            ExecutionResult(
                execution_id=leases[0].execution_id,
                status=ExecutionStatus.SUCCESS,
                exit_code=0,
                stdout="already done",
                stderr="",
                duration_ms=1,
                backend="fake",
            ),
        )
        authoritative = ExecutionResult(
            execution_id=leases[1].execution_id,
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="remote done",
            stderr="",
            duration_ms=2,
            backend="remote-fake",
        )
        reconciler = FakeReconciler({leases[1].execution_id: authoritative})
        reconciliation = ExecutionReconciliationService(
            session_manager=sessions,
            backend_reconciler=reconciler,
        )

        result = RunExecutionReconciliationService(
            session_manager=sessions,
            reconciliation_service=reconciliation,
        ).reconcile_backend(run_id)

        self.assertEqual(result.items[0].status, ReconciliationStatus.COMPLETED)
        self.assertEqual(result.items[1].status, ReconciliationStatus.COMPLETED)
        self.assertEqual(reconciler.calls, [(leases[1].execution_id, leases[1].idempotency_key)])
        self.assertEqual(len(sessions.snapshot(run_id).execution_results), 2)

    def test_backend_unavailable_never_authorizes_retry(self):
        sessions, run_id, _leases = self._session_with_leases()
        result = RunExecutionReconciliationService(
            session_manager=sessions,
            reconciliation_service=ExecutionReconciliationService(session_manager=sessions),
        ).reconcile_backend(run_id)

        self.assertEqual(len(result.pending), 2)
        self.assertTrue(
            all(item.status == ReconciliationStatus.BACKEND_UNAVAILABLE for item in result.items)
        )


if __name__ == "__main__":
    unittest.main()
