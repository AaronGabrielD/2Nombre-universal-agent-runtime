import unittest

from app.core.contracts import ExecutionRequest, ExecutionStatus
from app.runtime.bootstrap import _UnavailableTestExecutionBackend


class RuntimeBootstrapTests(unittest.TestCase):
    def test_test_backend_is_unavailable_and_does_not_execute(self):
        backend = _UnavailableTestExecutionBackend()
        self.assertEqual(backend.info.backend_id, "test")
        self.assertFalse(backend.info.available)

        result = backend.execute(
            ExecutionRequest(
                execution_id="exec-test",
                run_id="run-test",
                worker_id="worker-test",
                language="python",
                code="raise RuntimeError('must not execute')",
            )
        )
        self.assertEqual(result.status, ExecutionStatus.UNAVAILABLE)
        self.assertEqual(result.backend, "test")


if __name__ == "__main__":
    unittest.main()
