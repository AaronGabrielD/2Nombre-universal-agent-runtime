import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.execution.colab_service import (
    ColabCodeExecutor,
    ColabExecutionServiceError,
    ExecutionServiceConfig,
    RuntimeColabHTTPServer,
    _execution_environment,
    _safe_environment_key,
)


class ColabServiceTests(unittest.TestCase):
    def _config(self, root: str) -> ExecutionServiceConfig:
        with patch.dict(
            os.environ,
            {
                "RUNTIME_EXECUTION_TOKEN": "test-token",
                "RUNTIME_ARTIFACT_ROOT": root,
                "RUNTIME_ALLOW_NETWORK": "false",
            },
            clear=False,
        ):
            return ExecutionServiceConfig()

    def test_configuration_requires_execution_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ColabExecutionServiceError):
                ExecutionServiceConfig()

    def test_environment_filters_secret_like_names(self):
        self.assertFalse(_safe_environment_key("GEMINI_API_KEY"))
        self.assertFalse(_safe_environment_key("SERVICE_TOKEN"))
        self.assertFalse(_safe_environment_key("PRIVATE_VALUE"))
        self.assertTrue(_safe_environment_key("APP_MODE"))

        with tempfile.TemporaryDirectory() as tmp:
            env = _execution_environment(
                {"APP_MODE": "test", "GEMINI_API_KEY": "must-not-pass"},
                Path(tmp),
            )
            self.assertEqual(env["APP_MODE"], "test")
            self.assertNotIn("GEMINI_API_KEY", env)

    def test_request_validation_rejects_invalid_identifiers_and_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = ColabCodeExecutor(self._config(tmp))
            with self.assertRaises(ColabExecutionServiceError):
                executor._validate_request(
                    {
                        "execution_id": "../escape",
                        "run_id": "run-1",
                        "worker_id": "worker-1",
                        "language": "python",
                        "code": "print('x')",
                    }
                )
            with self.assertRaises(ColabExecutionServiceError):
                executor._validate_request(
                    {
                        "execution_id": "exec-1",
                        "run_id": "run-1",
                        "worker_id": "worker-1",
                        "language": "python",
                        "code": "print('x')",
                        "idempotency_key": "key-invalid-timeout",
                        "timeout_seconds": 0,
                    }
                )

    def test_network_request_is_denied_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = ColabCodeExecutor(self._config(tmp))
            result = executor.execute(
                {
                    "execution_id": "exec-1",
                    "run_id": "run-1",
                    "worker_id": "worker-1",
                    "language": "python",
                    "code": "print('x')",
                    "idempotency_key": "key-network-denied",
                    "needs_network": True,
                }
            )
            self.assertEqual(result["status"], "denied")
            self.assertEqual(result["exit_code"], None)

    def test_unsupported_language_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = ColabCodeExecutor(self._config(tmp))
            result = executor.execute(
                {
                    "execution_id": "exec-2",
                    "run_id": "run-1",
                    "worker_id": "worker-1",
                    "language": "ruby",
                    "code": "puts 'x'",
                    "idempotency_key": "key-unsupported-language",
                }
            )
            self.assertEqual(result["status"], "unavailable")

    def test_server_uses_shared_durable_execution_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(tmp)
            server = RuntimeColabHTTPServer(("127.0.0.1", 0), config)
            try:
                self.assertIs(server.executor.store, server.execution_store)
                self.assertEqual(server.runtime_config.execution_db_path, config.execution_db_path)
            finally:
                server.server_close()

    def test_symlinked_artifacts_are_never_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = ColabCodeExecutor(self._config(tmp))
            workdir = Path(tmp) / "work"
            execution_root = Path(tmp) / "artifacts" / "exec-symlink"
            workdir.mkdir()
            execution_root.mkdir(parents=True)
            target = Path(tmp) / "outside-secret.txt"
            target.write_text("must-not-export", encoding="utf-8")
            link = workdir / "leak.txt"
            try:
                link.symlink_to(target)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            artifacts = executor._collect_artifacts(workdir, execution_root, "exec-symlink")
            self.assertEqual(artifacts, [])
            self.assertFalse((execution_root / "leak.txt").exists())


if __name__ == "__main__":
    unittest.main()