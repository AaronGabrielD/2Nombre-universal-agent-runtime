import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.execution.colab_reconciler import ColabExecutionReconciler, ColabReconcilerError
from app.execution.colab_service import ColabCodeExecutor
from app.execution.colab_service import ExecutionServiceConfig


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class M41ColabReconciliationTests(unittest.TestCase):
    def test_executor_persists_and_reloads_result_without_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                "os.environ",
                {
                    "RUNTIME_EXECUTION_TOKEN": "test-token",
                    "RUNTIME_ARTIFACT_ROOT": tmp,
                },
                clear=False,
            ):
                config = ExecutionServiceConfig()
            executor = ColabCodeExecutor(config)
            payload = {
                "execution_id": "exec-41",
                "run_id": "run-41",
                "worker_id": "worker-41",
                "language": "python",
                "code": "print('ok')",
                "timeout_seconds": 10,
                "needs_network": False,
                "environment": {},
            }
            result = executor.execute(payload)
            executor.persist_result(result)
            evidence = executor.get_result("exec-41")
            self.assertEqual(evidence["execution_id"], "exec-41")
            self.assertEqual(evidence["status"], "success")
            self.assertNotIn("code", evidence)
            self.assertTrue((Path(tmp) / ".execution-evidence" / "exec-41.json").is_file())

    def test_client_reconciles_authoritative_result(self):
        payload = {
            "execution_id": "exec-41",
            "status": "success",
            "stdout": "ok",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 12,
            "artifacts": [],
            "backend": "colab-service",
        }
        response = FakeResponse(payload)
        reconciler = ColabExecutionReconciler(
            base_url="http://127.0.0.1:8000",
            token="test-token",
        )
        with patch("app.execution.colab_reconciler.urlopen", return_value=response):
            result = reconciler.reconcile(
                execution_id="exec-41",
                idempotency_key="key-41",
            )
        self.assertEqual(result.execution_id, "exec-41")
        self.assertEqual(result.status.value, "success")

    def test_client_rejects_mismatched_execution_id(self):
        payload = {
            "execution_id": "other-execution",
            "status": "success",
            "stdout": "ok",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 1,
            "artifacts": [],
            "backend": "colab-service",
        }
        reconciler = ColabExecutionReconciler(
            base_url="http://127.0.0.1:8000",
            token="test-token",
        )
        with patch(
            "app.execution.colab_reconciler.urlopen",
            return_value=FakeResponse(payload),
        ):
            with self.assertRaises(ColabReconcilerError):
                reconciler.reconcile(
                    execution_id="exec-41",
                    idempotency_key="key-41",
                )


if __name__ == "__main__":
    unittest.main()
