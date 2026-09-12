import threading
import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.session.manager import SessionManager
from app.session.models import WorkerOutput


class SessionConcurrencyTests(unittest.TestCase):
    def test_concurrent_execution_results_are_not_lost(self):
        sessions = SessionManager()
        context = sessions.create_session()
        barrier = threading.Barrier(8)
        errors = []
        errors_lock = threading.Lock()

        def writer(index: int) -> None:
            try:
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
            except Exception as exc:  # pragma: no cover - assertion below reports failures
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        results = sessions.snapshot(context.run_id).execution_results
        self.assertEqual(len(results), 8)
        self.assertEqual({item.execution_id for item in results}, {f"exec-{i}" for i in range(8)})

    def test_snapshot_isolated_during_concurrent_worker_updates(self):
        sessions = SessionManager()
        context = sessions.create_session()
        start_writers = threading.Event()
        errors = []
        errors_lock = threading.Lock()

        def writer(index: int) -> None:
            try:
                start_writers.wait()
                sessions.set_worker_output(
                    context.run_id,
                    WorkerOutput(
                        worker_id=f"worker-{index}",
                        run_id=context.run_id,
                        status="success",
                        output={"worker_index": index},
                    ),
                )
            except Exception as exc:  # pragma: no cover - assertion below reports failures
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        snapshot_before = sessions.snapshot(context.run_id)
        start_writers.set()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(snapshot_before.worker_outputs, {})
        final = sessions.snapshot(context.run_id).worker_outputs
        self.assertEqual(len(final), 4)
        self.assertEqual(set(final), {f"worker-{i}" for i in range(4)})
        self.assertEqual({output.output["worker_index"] for output in final.values()}, {0, 1, 2, 3})


if __name__ == "__main__":
    unittest.main()
