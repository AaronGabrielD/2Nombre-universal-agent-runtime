import os
import threading
import unittest
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.core.contracts import ExecutionRequest, ExecutionStatus
from app.execution.colab import ColabBackendError, ColabExecutionBackend
from app.execution.colab_service import ExecutionServiceConfig, RuntimeColabHTTPServer


class M20HttpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._old = {
            key: os.environ.get(key)
            for key in (
                "RUNTIME_EXECUTION_TOKEN",
                "RUNTIME_ARTIFACT_ROOT",
                "RUNTIME_ALLOW_NETWORK",
            )
        }
        os.environ["RUNTIME_EXECUTION_TOKEN"] = "integration-test-token"
        os.environ["RUNTIME_ARTIFACT_ROOT"] = self._tmp.name
        os.environ["RUNTIME_ALLOW_NETWORK"] = "false"
        self.config = ExecutionServiceConfig()
        self.server = RuntimeColabHTTPServer(("127.0.0.1", 0), self.config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        self.backend = ColabExecutionBackend(
            base_url=self.base_url,
            token="integration-test-token",
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

    def request(
        self,
        *,
        code="print('integration-ok')",
        needs_network=False,
        execution_id="exec-m20",
        idempotency_key=None,
    ):
        key = idempotency_key or f"idem-{execution_id}"
        return ExecutionRequest(
            execution_id=execution_id,
            run_id="run-m20",
            worker_id="worker-m20",
            language="python",
            code=code,
            timeout_seconds=5,
            needs_network=needs_network,
            environment={},
            idempotency_key=key,
        )

    def test_authenticated_http_execution_round_trip(self):
        result = self.backend.execute(self.request())
        self.assertEqual(result.execution_id, "exec-m20")
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertIn("integration-ok", result.stdout)
        self.assertEqual(result.backend, "colab")

    def test_duplicate_request_returns_same_durable_result(self):
        first = self.backend.execute(self.request(execution_id="exec-dedup"))
        second = self.backend.execute(self.request(execution_id="exec-dedup"))
        self.assertEqual(first, second)

        fetched = Request(
            f"{self.base_url}/executions/exec-dedup",
            headers={"Authorization": "Bearer integration-test-token"},
        )
        with urlopen(fetched, timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_reusing_execution_id_for_different_work_is_rejected(self):
        self.backend.execute(self.request(execution_id="exec-conflict", code="print('a')"))
        with self.assertRaises(ColabBackendError) as ctx:
            self.backend.execute(
                self.request(execution_id="exec-conflict", code="print('b')", idempotency_key="idem-other")
            )
        self.assertIn("HTTP 409", str(ctx.exception))

    def test_service_rejects_missing_bearer_token(self):
        with self.assertRaises(ColabBackendError) as ctx:
            ColabExecutionBackend(base_url=self.base_url, timeout_seconds=10).execute(self.request())
        self.assertIn("HTTP 401", str(ctx.exception))

    def test_network_policy_is_enforced_by_remote_service(self):
        result = self.backend.execute(
            self.request(needs_network=True, execution_id="exec-network")
        )
        self.assertEqual(result.status, ExecutionStatus.DENIED)
        self.assertIn("network execution is disabled", result.stderr)

    def test_artifact_is_returned_and_retrievable(self):
        execution_id = "exec-artifact"
        code = "from pathlib import Path; Path('artifact.txt').write_text('artifact-ok')"
        result = self.backend.execute(self.request(code=code, execution_id=execution_id))
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertEqual(len(result.artifacts), 1)
        artifact = result.artifacts[0]
        self.assertEqual(artifact.name, "artifact.txt")
        self.assertTrue(artifact.uri.startswith(f"artifact://{execution_id}/"))
        request = Request(
            f"{self.base_url}/artifacts/{execution_id}/{artifact.name}",
            headers={"Authorization": "Bearer integration-test-token"},
        )
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.read(), b"artifact-ok")

    def test_oversized_artifact_is_not_exposed(self):
        old_limit = self.config.max_artifact_bytes
        self.config.max_artifact_bytes = 4
        result = self.server.executor.execute(
            {
                "execution_id": "exec-large-artifact",
                "run_id": "run-m20",
                "worker_id": "worker-m20",
                "language": "python",
                "code": "from pathlib import Path; Path('big.txt').write_text('123456789')",
                "timeout_seconds": 5,
                "idempotency_key": "idem-large-artifact",
            }
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["artifacts"], [])
        self.config.max_artifact_bytes = old_limit

    def test_unknown_execution_endpoint_is_not_successful(self):
        request = Request(
            f"{self.base_url}/executions/missing-execution",
            headers={"Authorization": "Bearer integration-test-token"},
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
