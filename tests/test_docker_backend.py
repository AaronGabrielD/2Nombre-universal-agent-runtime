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
            captured["env"] = env
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
        self.assertTrue(str(captured["env"]["PATH"]).startswith("/usr/bin"))

    def test_docker_path_contains_directory_not_binary_path(self):
        request = ExecutionRequest(
            execution_id="exec-path-contract",
            run_id="run-path-contract",
            worker_id="worker-1",
            language="python",
            code="print('ok')",
        )
        captured: dict[str, object] = {}

        def fake_run(command, *, cwd, env, timeout, max_output_bytes):
            captured["env"] = env
            return SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"", timed_out=False)

        backend = DockerExecutionBackend()
        with patch("app.execution.docker_backend.shutil.which", return_value="/opt/docker/bin/docker"):
            with patch("app.execution.docker_backend.run_bounded_process", side_effect=fake_run):
                backend.execute(request)

        path_value = str(captured["env"]["PATH"])
        self.assertTrue(path_value.startswith("/opt/docker/bin"))
        self.assertNotEqual(path_value.split(":", 1)[0], "/opt/docker/bin/docker")


if __name__ == "__main__":
    import unittest

    unittest.main()
