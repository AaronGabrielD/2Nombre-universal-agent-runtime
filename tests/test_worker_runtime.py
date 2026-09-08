import threading
import time
import unittest

from app.core.config import Settings
from app.core.contracts import ExecutionResult, ExecutionStatus, TaskSpec
from app.execution import ExecutionAuthorization, ExecutionBackend, ExecutionBackendInfo, ExecutionGateway
from app.session.manager import SessionManager
from app.workers.models import DispatchBatch, WorkerInstance
from app.workers.runtime import WorkerExecutionTask, WorkerRuntimeAdapter, WorkerRuntimeError


def test_settings():
    return Settings(
        gemini_api_key=None,
        gemini_model_architect="architect",
        gemini_model_worker="worker",
        gemini_model_supervisor="supervisor",
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


class FakeBackend(ExecutionBackend):
    def __init__(self, *, delay: float = 0.0, concurrency: list[int] | None = None):
        self.delay = delay
        self.concurrency = concurrency
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0

    @property
    def info(self):
        return ExecutionBackendInfo("test", "Test")

    def execute(self, request):
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            if self.concurrency is not None:
                self.concurrency.append(self._active)
        try:
            if self.delay:
                time.sleep(self.delay)
            return ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.SUCCESS,
                exit_code=0,
                stdout=request.code,
                stderr="",
                duration_ms=1,
                backend="test",
            )
        finally:
            with self._lock:
                self._active -= 1


def batch(run_id="run-1", worker_ids=("worker-1",)):
    workers = tuple(
        WorkerInstance(
            worker_id=worker_id,
            role="builder",
            mission="build",
            deliverables=("result",),
            required_tools=(),
            dependencies=(),
            can_request_human_input=True,
            run_id=run_id,
        )
        for worker_id in worker_ids
    )
    return DispatchBatch(run_id=run_id, workers=workers, sequence=0)


def task(worker_id="worker-1", task_id=None):
    return WorkerExecutionTask(
        task=TaskSpec(
            task_id=task_id or f"task-{worker_id}",
            worker_id=worker_id,
            description="execute work",
            expected_output="result",
        ),
        language="python",
        code=f"print('{worker_id}')",
    )


class WorkerRuntimeTests(unittest.TestCase):
    def make_adapter(self, sessions, backend=None):
        gateway = ExecutionGateway(
            backends=(backend or FakeBackend(),),
            settings=test_settings(),
        )
        return WorkerRuntimeAdapter(gateway=gateway, session_manager=sessions)

    def test_denied_authorization_fails_closed_without_backend_execution(self):
        sessions = SessionManager()
        context = sessions.create_session()
        backend = FakeBackend()
        adapter = self.make_adapter(sessions, backend)

        result = adapter.execute_batch(
            batch=batch(context.run_id),
            tasks=(task(),),
            authorization=ExecutionAuthorization(False, "Gate C not approved"),
        )

        self.assertEqual(result[0].status, ExecutionStatus.DENIED)
        self.assertEqual(backend.max_active, 0)
        self.assertEqual(len(sessions.snapshot(context.run_id).execution_results), 1)

    def test_authorized_task_is_sent_through_gateway_and_persisted(self):
        sessions = SessionManager()
        context = sessions.create_session()
        adapter = self.make_adapter(sessions)

        results = adapter.execute_batch(
            batch=batch(context.run_id),
            tasks=(task(),),
            authorization=ExecutionAuthorization(True, gate_id="gate-c"),
        )

        self.assertEqual(results[0].status, ExecutionStatus.SUCCESS)
        self.assertEqual(results[0].backend, "test")
        stored = sessions.snapshot(context.run_id).execution_results
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].execution_id, results[0].execution_id)

    def test_task_from_another_worker_is_rejected(self):
        sessions = SessionManager()
        context = sessions.create_session()
        adapter = self.make_adapter(sessions)

        with self.assertRaises(WorkerRuntimeError):
            adapter.execute_batch(
                batch=batch(context.run_id, ("worker-1",)),
                tasks=(task("worker-2"),),
                authorization=ExecutionAuthorization(True),
            )

        self.assertEqual(sessions.snapshot(context.run_id).execution_results, [])

    def test_worker_from_another_run_is_rejected(self):
        sessions = SessionManager()
        context = sessions.create_session()
        foreign_batch = batch("different-run")
        adapter = self.make_adapter(sessions)

        with self.assertRaises(WorkerRuntimeError):
            adapter.execute_batch(
                batch=foreign_batch,
                tasks=(task(),),
                authorization=ExecutionAuthorization(True),
            )

        self.assertEqual(sessions.snapshot(context.run_id).execution_results, [])

    def test_execution_task_requires_code(self):
        with self.assertRaises(WorkerRuntimeError):
            WorkerExecutionTask(
                task=TaskSpec(
                    task_id="task-1",
                    worker_id="worker-1",
                    description="execute",
                    expected_output="result",
                ),
                language="python",
                code="   ",
            ).validate()

    def test_parallel_execution_overlaps_independent_tasks_and_preserves_order(self):
        sessions = SessionManager()
        context = sessions.create_session()
        backend = FakeBackend(delay=0.05)
        adapter = self.make_adapter(sessions, backend)
        worker_ids = ("worker-a", "worker-b", "worker-c")
        worker_batch = batch(context.run_id, worker_ids)
        tasks = tuple(task(worker_id) for worker_id in worker_ids)

        started = time.perf_counter()
        results = adapter.execute_batch(
            batch=worker_batch,
            tasks=tasks,
            authorization=ExecutionAuthorization(True),
            parallel=True,
        )
        elapsed = time.perf_counter() - started

        self.assertEqual(len(results), 3)
        self.assertEqual([result.stdout for result in results], list(worker_ids))
        self.assertGreaterEqual(backend.max_active, 2)
        self.assertLess(elapsed, 0.14)
        self.assertEqual(len(sessions.snapshot(context.run_id).execution_results), 3)

    def test_parallel_batch_rejects_duplicate_worker_tasks_before_threads_start(self):
        sessions = SessionManager()
        context = sessions.create_session()
        backend = FakeBackend()
        adapter = self.make_adapter(sessions, backend)
        worker_batch = batch(context.run_id, ("worker-a", "worker-b"))
        tasks = (task("worker-a", "task-a"), task("worker-a", "task-b"))

        with self.assertRaises(WorkerRuntimeError):
            adapter.execute_batch(
                batch=worker_batch,
                tasks=tasks,
                authorization=ExecutionAuthorization(True),
                parallel=True,
            )

        self.assertEqual(backend.max_active, 0)
        self.assertEqual(sessions.snapshot(context.run_id).execution_results, [])


if __name__ == "__main__":
    unittest.main()
