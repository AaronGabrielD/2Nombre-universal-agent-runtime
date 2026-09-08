from __future__ import annotations

import unittest

from app.core.config import Settings
from app.core.contracts import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.execution import ExecutionAuthorization, ExecutionBackend, ExecutionBackendInfo, ExecutionGateway


def settings(**overrides):
    values = dict(
        gemini_api_key=None,
        gemini_model_architect="test-model",
        gemini_model_worker="test-worker",
        gemini_model_supervisor="test-supervisor",
        gemini_temperature=0.2,
        max_workers=4,
        min_workers=3,
        default_execution_timeout_seconds=60,
        max_uploads_per_message=20,
        max_upload_size_mb=100,
        execution_backend="test",
        execution_gateway_url=None,
        execution_gateway_token=None,
    )
    values.update(overrides)
    return Settings(**values)


def request(execution_id="exec-1"):
    return ExecutionRequest(
        execution_id=execution_id,
        run_id="run-1",
        worker_id="worker-1",
        language="python",
        code="print('ok')",
        timeout_seconds=30,
    )


class FakeBackend(ExecutionBackend):
    def __init__(self, backend_id="test", available=True, mode="success"):
        self._info = ExecutionBackendInfo(backend_id, backend_id.title(), available)
        self.mode = mode
        self.calls = 0

    @property
    def info(self):
        return self._info

    def execute(self, req):
        self.calls += 1
        if self.mode == "timeout":
            raise TimeoutError("timed out")
        if self.mode == "error":
            raise RuntimeError("backend exploded")
        return ExecutionResult(
            execution_id=req.execution_id,
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
            backend=self.info.backend_id,
        )


class ExecutionGatewayTests(unittest.TestCase):
    def test_denied_execution_never_calls_backend(self):
        backend = FakeBackend()
        gateway = ExecutionGateway(backends=(backend,), settings=settings())
        result = gateway.execute(request(), authorization=ExecutionAuthorization(False, "human approval required"))
        self.assertEqual(result.status, ExecutionStatus.DENIED)
        self.assertEqual(backend.calls, 0)

    def test_authorized_execution_delegates_to_selected_backend(self):
        backend = FakeBackend()
        gateway = ExecutionGateway(backends=(backend,), settings=settings())
        result = gateway.execute(request(), authorization=ExecutionAuthorization(True, gate_id="gate-1"))
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.backend, "test")
        self.assertEqual(backend.calls, 1)

    def test_unknown_backend_fails_closed(self):
        gateway = ExecutionGateway(backends=(), settings=settings())
        result = gateway.execute(request(), authorization=ExecutionAuthorization(True))
        self.assertEqual(result.status, ExecutionStatus.UNAVAILABLE)

    def test_unavailable_backend_fails_closed(self):
        backend = FakeBackend(available=False)
        gateway = ExecutionGateway(backends=(backend,), settings=settings())
        result = gateway.execute(request(), authorization=ExecutionAuthorization(True))
        self.assertEqual(result.status, ExecutionStatus.UNAVAILABLE)
        self.assertEqual(backend.calls, 0)

    def test_backend_timeout_is_normalized(self):
        backend = FakeBackend(mode="timeout")
        gateway = ExecutionGateway(backends=(backend,), settings=settings())
        result = gateway.execute(request(), authorization=ExecutionAuthorization(True))
        self.assertEqual(result.status, ExecutionStatus.TIMEOUT)
        self.assertIn("timed out", result.stderr)

    def test_backend_error_is_normalized(self):
        backend = FakeBackend(mode="error")
        gateway = ExecutionGateway(backends=(backend,), settings=settings())
        result = gateway.execute(request(), authorization=ExecutionAuthorization(True))
        self.assertEqual(result.status, ExecutionStatus.ERROR)
        self.assertIn("backend exploded", result.stderr)

    def test_backend_must_return_matching_execution_id(self):
        class WrongIdBackend(FakeBackend):
            def execute(self, req):
                self.calls += 1
                return ExecutionResult(
                    execution_id="wrong",
                    status=ExecutionStatus.SUCCESS,
                    exit_code=0,
                    stdout="",
                    stderr="",
                    duration_ms=0,
                    backend=self.info.backend_id,
                )

        gateway = ExecutionGateway(backends=(WrongIdBackend(),), settings=settings())
        with self.assertRaises(RuntimeError):
            gateway.execute(request(), authorization=ExecutionAuthorization(True))


if __name__ == "__main__":
    unittest.main()
