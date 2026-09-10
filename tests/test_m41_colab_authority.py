import os
import threading
import unittest
from tempfile import TemporaryDirectory

from app.core.contracts import ExecutionStatus
from app.execution.colab import ColabExecutionBackend
from app.execution.colab_authority import (
    AuthoritativeColabHTTPServer,
    ColabAuthorityError,
    ColabExecutionReconciler,
)
from app.execution.colab_service import ExecutionServiceConfig
from app.execution.reconciliation import ExecutionReconciliationService, ReconciliationStatus
from app.session.manager import SessionManager


class M41ColabAuthorityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._old = {
            key: os.environ.get(key)
            for key in ("RUNTIME_EXECUTION_TOKEN", "RUNTIME_ARTIFACT_ROOT", "RUNTIME_ALLOW_NETWORK")
        }
        os.environ["RUNTIME_EXECUTION_TOKEN"] = "m41-token"
        os.environ["RUNTIME_ARTIFACT_ROOT"] = self._tmp.name
        os.environ["RUNTIME_ALLOW_NETWORK"] = "false"
        self.config = ExecutionServiceConfig()
        self.server = AuthoritativeColabHTTPServer(("127.0.0.1", 0), self.config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        self.backend = ColabExecutionBackend(
            base_url=self.base_url,
            token="m41-token",
            timeout_seconds=10,
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self._tmp.cleanup()
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_execution_is_durably_reconcilable_after_server_restart(self):
        from app.core.contracts import ExecutionRequest

        request = ExecutionRequest(
            execution_id="exec-m41",
            run_id="run-m41",
            worker_id="worker-m41",
            language="python",
            code="print('m41-ok')",
            timeout_seconds=5,
        )
        executed = self.backend.execute(request)
        self.assertEqual(executed.status, ExecutionStatus.SUCCESS)

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

        restarted = AuthoritativeColabHTTPServer(("127.0.0.1", 0), self.config)
        restarted_thread = threading.Thread(target=restarted.serve_forever, daemon=True)
        restarted_thread.start()
        try:
            host, port = restarted.server_address
            reconciler = ColabExecutionReconciler(
                base_url=f"http://{host}:{port}",
                token="m41-token",
            )
            result = reconciler.reconcile(
                execution_id="exec-m41",
                idempotency_key="persisted-test-key",
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.status, ExecutionStatus.SUCCESS)
            self.assertEqual(result.stdout.strip(), "m41-ok")
        finally:
            restarted.shutdown()
            restarted.server_close()
            restarted_thread.join(timeout=2)
            self.server = restarted

    def test_missing_execution_returns_no_authoritative_result(self):
        reconciler = ColabExecutionReconciler(base_url=self.base_url, token="m41-token")
        self.assertIsNone(
            reconciler.reconcile(
                execution_id="exec-missing",
                idempotency_key="key-missing",
            )
        )

    def test_missing_credentials_fail_closed(self):
        reconciler = ColabExecutionReconciler(base_url=self.base_url)
        with self.assertRaises(ColabAuthorityError) as ctx:
            reconciler.reconcile(
                execution_id="exec-missing-auth",
                idempotency_key="key-auth",
            )
        self.assertIn("HTTP 401", str(ctx.exception))

    def test_authoritative_reconciliation_persists_into_runtime_session(self):
        from app.core.contracts import ExecutionRequest
        from app.execution.lease import ExecutionLeaseService

        sessions = SessionManager()
        run = sessions.create_session()
        leases = ExecutionLeaseService(session_manager=sessions)
        key = "m41-session-key"
        lease = leases.reserve(
            run_id=run.run_id,
            worker_id="worker-m41",
            task_id="task-m41",
            idempotency_key=key,
            execution_id="exec-m41-session",
        )
        executed = self.backend.execute(
            ExecutionRequest(
                execution_id=lease.execution_id,
                run_id=run.run_id,
                worker_id=lease.worker_id,
                language="python",
                code="print('session-ok')",
                timeout_seconds=5,
            )
        )
        self.assertEqual(executed.status, ExecutionStatus.SUCCESS)

        service = ExecutionReconciliationService(
            session_manager=sessions,
            backend_reconciler=ColabExecutionReconciler(
                base_url=self.base_url,
                token="m41-token",
            ),
        )
        result = service.reconcile_backend(
            run_id=run.run_id,
            idempotency_key=key,
        )
        self.assertEqual(result.status, ReconciliationStatus.COMPLETED)
        self.assertEqual(len(sessions.snapshot(run.run_id).execution_results), 1)


if __name__ == "__main__":
    unittest.main()
