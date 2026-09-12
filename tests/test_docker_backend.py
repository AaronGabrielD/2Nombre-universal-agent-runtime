from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.core.contracts import ExecutionRequest, ExecutionStatus
from app.execution.docker_backend import DockerExecutionBackend


class DockerBackendTests(TestCase):
    def test_execute_passes_request_timeout_without_hidden_grace_period(self):
        request = ExecutionRequest(
            execution_id="exec-timeout-contract",
            run_id="run-timeout-contract",
            worker_id="worker-1",
            language="python",
            code="print('ok')",
            timeout_seconds=17,
        )
        captured: dict[str, object] = {}

        def fake_run(command, *, cwd, env, timeout, max_output_bytes):
            captured["command"] = command
            captured["timeout"] = timeout
            captured["max_output_bytes"] = max_output_bytes
            return SimpleNamespace(returncode=0, stdout=b"ok\n", stderr=b"", timed_out=False)

        backend = DockerExecutionBackend(docker_binary="docker")
        with patch("app.execution.docker_backend.shutil.which", return_value="/usr/bin/docker"):
            with patch("app.execution.docker_backend.run_bounded_process", side_effect=fake_run):
                result = backend.execute(request)

        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertEqual(captured["timeout"], 17)
        self.assertIn("docker", captured["command"])


if __name__ == "__main__":
    import unittest

    unittest.main()
