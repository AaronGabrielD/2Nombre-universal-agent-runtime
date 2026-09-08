from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.core.contracts import ExecutionRequest, ExecutionStatus
from app.execution import ColabBackendError, ColabExecutionBackend


class FakeResponse:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._data


def make_request():
    return ExecutionRequest(
        execution_id="exec-1",
        run_id="run-1",
        worker_id="worker-1",
        language="python",
        code="print('ok')",
        timeout_seconds=30,
    )


class ColabBackendTests(unittest.TestCase):
    def test_rejects_invalid_url(self):
        with self.assertRaises(ValueError):
            ColabExecutionBackend(base_url="not-a-url")

    def test_posts_json_and_returns_result(self):
        backend = ColabExecutionBackend(
            base_url="https://example.test/runtime/",
            token="test-token",
            timeout_seconds=20,
        )
        payload = {
            "execution_id": "exec-1",
            "status": "success",
            "exit_code": 0,
            "stdout": "ok\n",
            "stderr": "",
            "duration_ms": 12,
            "backend": "colab",
            "artifacts": [],
        }
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["method"] = req.method
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse(payload)

        with patch("app.execution.colab.urlopen", side_effect=fake_urlopen):
            result = backend.execute(make_request())

        self.assertEqual(captured["url"], "https://example.test/runtime/execute")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["body"]["execution_id"], "exec-1")
        self.assertEqual(captured["timeout"], 20)
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.stdout, "ok\n")

    def test_rejects_response_with_wrong_execution_id(self):
        backend = ColabExecutionBackend(base_url="https://example.test")
        payload = {
            "execution_id": "wrong",
            "status": "success",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "duration_ms": 1,
            "artifacts": [],
        }
        with patch("app.execution.colab.urlopen", return_value=FakeResponse(payload)):
            with self.assertRaises(ColabBackendError):
                backend.execute(make_request())

    def test_rejects_unknown_status(self):
        backend = ColabExecutionBackend(base_url="https://example.test")
        payload = {
            "execution_id": "exec-1",
            "status": "unknown-status",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "duration_ms": 1,
            "artifacts": [],
        }
        with patch("app.execution.colab.urlopen", return_value=FakeResponse(payload)):
            with self.assertRaises(ColabBackendError):
                backend.execute(make_request())

    def test_parses_artifacts(self):
        backend = ColabExecutionBackend(base_url="https://example.test")
        payload = {
            "execution_id": "exec-1",
            "status": "success",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "duration_ms": 1,
            "artifacts": [
                {
                    "artifact_id": "a1",
                    "name": "result.txt",
                    "uri": "https://example.test/result.txt",
                }
            ],
        }
        with patch("app.execution.colab.urlopen", return_value=FakeResponse(payload)):
            result = backend.execute(make_request())
        self.assertEqual(result.artifacts[0].artifact_id, "a1")
        self.assertEqual(result.artifacts[0].name, "result.txt")


if __name__ == "__main__":
    unittest.main()
