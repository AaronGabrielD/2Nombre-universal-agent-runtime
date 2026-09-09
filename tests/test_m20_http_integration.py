import os
import threading
import unittest
from tempfile import TemporaryDirectory

from app.core.contracts import ExecutionRequest, ExecutionStatus
from app.execution.colab import ColabExecutionBackend, ColabBackendError
from app.execution.models import ExecutionAuthorization
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
        self.backend = ColabExecutionBackend(
            base_url=f"http://{host}:{port}",
            token="integration-test-token",
            timeout_seconds=10,
        )
        self.authorization = ExecutionAuthorization(
            authorized=True,
            reason="integration test",
            gate_id="gate-test",
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

    def request(self, *, code="print('integration-ok')", needs_network=False):
        return ExecutionRequest(
            execution_id="exec-m20",
            run_id="run-m20",
            worker_id="worker-m20",
            language="python",
            code=code,
            timeout_seconds=5,
            needs_network=needs_network,
            environment={},
        )

    def test_authenticated_http_execution_round_trip(self):
        result = self.backend.execute(self.request(), authorization=self.authorization)
        self.assertEqual(result.execution_id, "exec-m20")
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertIn("integration-ok", result.stdout)
        self.assertEqual(result.backend, "colab-service")

    def test_service_rejects_missing_bearer_token(self):
        unauthenticated = ColabExecutionBackend(
            base_url=f"http://{self.server.server_address[0]}:{self.server.server_address[1]}",
            timeout_seconds=10,
        )
        with self.assertRaises(ColabBackendError) as ctx:
            unauthenticated.execute(self.request())
        self.assertIn("HTTP 401", str(ctx.exception))

    def test_network_policy_is_enforced_by_remote_service(self):
        result = self.backend.execute(self.request(needs_network=True), authorization=self.authorization)
        self.assertEqual(result.status, ExecutionStatus.ERROR)
        self.assertIn("network execution is disabled", result.stderr)

    def test_artifact_is_returned_and_retrievable(self):
        code = "from pathlib import Path; Path('artifact.txt').write_text('artifact-ok')"
        result = self.backend.execute(self.request(code=code), authorization=self.authorization)
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertEqual(len(result.artifacts), 1)
        self.assertTrue(result.artifacts[0].uri.startswith("artifact://exec-m20/"))


if __name__ == "__main__":
    unittest.main()
