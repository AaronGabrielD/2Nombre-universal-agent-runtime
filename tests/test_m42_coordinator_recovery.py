import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.core.states import WorkflowState
from app.execution.lease import ExecutionLeaseService
from app.execution.reconciliation import ExecutionReconciler, ExecutionReconciliationService, ReconciliationStatus
from app.recovery.models import RecoveryAction
from app.recovery.resume import RecoveryResumeService
from app.revision.service import RevisionService
from app.runtime.service import RuntimeCoordinator, RuntimeCoordinatorError
from app.session.manager import SessionManager


class FakeReconciler(ExecutionReconciler):
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def reconcile(self, *, execution_id: str, idempotency_key: str) -> ExecutionResult | None:
        self.calls += 1
        return self.result


class M42CoordinatorRecoveryTests(unittest.TestCase):
    def test_inspect_recovery_is_exposed_by_coordinator(self):
        sessions = SessionManager()
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)

        coordinator = RuntimeCoordinator(session_manager=sessions)
        checkpoint = coordinator.inspect_recovery(run.run_id)

        self.assertEqual(checkpoint.run_id, run.run_id)
        self.assertEqual(checkpoint.state, WorkflowState.ARCHITECTING)
        self.assertEqual(checkpoint.action, RecoveryAction.REBUILD_ARCHITECTURE)

    def test_revision_recovery_is_coordinated_and_audited(self):
        sessions = SessionManager()
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        sessions.transition(run.run_id, WorkflowState.EXECUTING)
        sessions.transition(run.run_id, WorkflowState.SUPERVISING)
        RevisionService(session_manager=sessions).request_revision(
            run.run_id,
            reason="QA requested architecture revision",
            source="test",
            feedback="rebuild the architecture",
        )

        coordinator = RuntimeCoordinator(session_manager=sessions)
        result = coordinator.resume_recovery(
            run_id=run.run_id,
            action=RecoveryAction.REBUILD_ARCHITECTURE,
        )

        self.assertEqual(result.resulting_state, WorkflowState.ARCHITECTING)
        self.assertTrue(result.audit_event_id)
        audit = [m for m in sessions.snapshot(run.run_id).messages if m.metadata.get("phase") == "recovery_resume"]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0].metadata["action"], RecoveryAction.REBUILD_ARCHITECTURE.value)

    def test_execution_recovery_is_delegated_to_canonical_recovery_service(self):
        sessions = SessionManager()
        run = sessions.create_session()
        for state in (
            WorkflowState.INTAKE,
            WorkflowState.ARCHITECTING,
            WorkflowState.WAITING_ARCHITECT_APPROVAL,
            WorkflowState.EXECUTING,
        ):
            sessions.transition(run.run_id, state)

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
                backend="fake",
            )
        )
        recovery = RecoveryResumeService(
            session_manager=sessions,
            reconciliation_service=ExecutionReconciliationService(
                session_manager=sessions,
                backend_reconciler=reconciler,
            ),
        )
        coordinator = RuntimeCoordinator(
            session_manager=sessions,
            recovery_resume_service=recovery,
        )

        result = coordinator.resume_recovery(
            run_id=run.run_id,
            action=RecoveryAction.RECONCILE_EXECUTION,
            idempotency_key=key,
        )

        self.assertEqual(result.resulting_state, WorkflowState.SUPERVISING)
        self.assertEqual(result.reconciliation.status, ReconciliationStatus.COMPLETED)
        self.assertEqual(reconciler.calls, 1)

    def test_invalid_recovery_action_is_wrapped_and_does_not_mutate(self):
        sessions = SessionManager()
        run = sessions.create_session()
        sessions.transition(run.run_id, WorkflowState.INTAKE)
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        coordinator = RuntimeCoordinator(session_manager=sessions)

        with self.assertRaises(RuntimeCoordinatorError):
            coordinator.resume_recovery(
                run_id=run.run_id,
                action=RecoveryAction.RESUME_SUPERVISION,
            )

        self.assertEqual(sessions.get_context(run.run_id).state, WorkflowState.ARCHITECTING)
