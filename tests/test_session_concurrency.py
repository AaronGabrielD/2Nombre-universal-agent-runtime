import threading
import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.session.manager import SessionManager


class SessionConcurrencyTests(unittest.TestCase):
    def test_concurrent_execution_results_are_not_lost(self):
        sessions = SessionManager()
        context = sessions.create_session()
        barrier = threading.Barrier(8)

        def writer(index: int) -> None:
            barrier.wait()
            sessions.add_execution_result(
                context.run_id,
                ExecutionResult(
                    execution_id=f"exec-{index}",
                    status=ExecutionStatus.SUCCESS,
                    exit_code=0,
                    stdout="ok",
                    stderr="",
                    duration_ms=1,
                    backend="test",
                ),
            )

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        results = sessions.snapshot(context.run_id).execution_results
        self.assertEqual(len(results), 8)
        self.assertEqual({item.execution_id for item in results}, {f"exec-{i}" for i in range(8)})

    def test_snapshot_isolated_during_concurrent_worker_updates(self):
        sessions = SessionManager()
        context = sessions.create_session()
        barrier = threading.Barrier(4)

        def writer(index: int) -> None:
            barrier.wait()
            from app.session.models import WorkerOutput
            sessions.set_worker_output(
                context.run_id,
                WorkerOutput(worker_id=f"worker-{index}", run_id=context.run_id, status="success"),
            )

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        snapshot_before = sessions.snapshot(context.run_id)
        for thread in threads:
            thread.join()

        self.assertEqual(snapshot_before.worker_outputs, {})
        self.assertEqual(len(sessions.snapshot(context.run_id).worker_outputs), 4)


if __name__ == "__main__":
    unittest.main()
