import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

from app.core.config import Settings
from app.core.contracts import ExecutionRequest, ExecutionStatus
from app.execution import ColabExecutionBackend
from app.execution.colab import ColabBackendError
from app.execution.colab_service import ColabRuntimeConfig, RuntimeColabHTTPServer


class M20HttpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.config = ColabRuntimeConfig(
            execution_token="integration-token",
            bind_host="127.0.0.1",
            port=0,
            allow_network=False,
            python_policy="restricted",
            artifact_root=str(Path(self._temp_dir.name) / "artifacts"),
        )
        self.service = RuntimeColabHTTPServer(self.config)
        self.service.start()
        host, port = self.service.address
        self.base_url = f"http://{host}:{port}"
        self.backend = ColabExecutionBackend(
            base_url=self.base_url,
            token=self.config.execution_token,
            timeout_seconds=10,
        )

    def tearDown(self):
        self.service.shutdown()
        self._temp_dir.cleanup()

    def request(self, *, code="print('integration-ok')", needs_network=False, execution_id="exec-m20"):
        return ExecutionRequest(
            execution_id=execution_id,
            run_id="run-m20",
            worker_id="worker-m20",
            language="python",
            code=code,
            timeout_seconds=10,
            needs_network=needs_network,
            environment={},
        )

    def test_authenticated_http_execution_round_trip(self):
        result = self.backend.execute(self.request())
        self.assertEqual(result.execution_id, "exec-m20")
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertIn("integration-ok", result.stdout)
        self.assertEqual(result.backend, "colab-service")

    def test_service_rejects_missing_bearer_token(self):
        unauthenticated = ColabExecutionBackend(base_url=self.base_url, timeout_seconds=10)
        with self.assertRaises(ColabBackendError) as ctx:
            unauthenticated.execute(self.request())
        self.assertIn("HTTP 401", str(ctx.exception))

    def test_network_policy_is_enforced_by_remote_service(self):
        result = self.backend.execute(self.request(needs_network=True, execution_id="exec-network"))
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

        url = f"{self.base_url}/artifacts/{execution_id}/{artifact.name}"
        with urlopen(url, timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read().decode("utf-8"), "artifact-ok")


if __name__ == "__main__":
    unittest.main()
