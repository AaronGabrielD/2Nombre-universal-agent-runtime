import unittest

from app.core.contracts import ExecutionResult, ExecutionStatus, TaskSpec
from app.execution import ExecutionAuthorization, ExecutionBackend, ExecutionBackendInfo, ExecutionGateway
from app.session.manager import SessionManager
from app.workers.models import DispatchBatch, WorkerInstance
from app.workers.runtime import WorkerExecutionTask, WorkerRuntimeAdapter, WorkerRuntimeError


class FakeBackend(ExecutionBackend):
    @property
    def info(self):
        return ExecutionBackendInfo("test", "Test")

    def execute(self, request):
        return ExecutionResult(
            execution_id=request.execution_id,
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout=request.code,
            stderr="",
            duration_ms=1,
            backend="test",
        )


def batch(run_id="run-1", worker_id="worker-1"):
    worker = WorkerInstance(
        worker_id=worker_id,
        role="builder",
        mission="build",
        deliverables=("result",),
        required_tools=(),
        dependencies=(),
        can_request_human_input=True,
        run_id=run_id,
    )
    return DispatchBatch(run_id=run_id, workers=(worker,), sequence=0)


def task(worker_id="worker-1"):
    return WorkerExecutionTask(
        task=TaskSpec(
            task_id="task-1",
            worker_id=worker_id,
            description="execute work",
            expected_output="result",
        ),
        language="python",
        code="print('ok')",
    )


class WorkerRuntimeTests(unittest.TestCase):
    def make_adapter(self, sessions):
        gateway = ExecutionGateway(backends=(FakeBackend(),), settings=None)
        return WorkerRuntimeAdapter(gateway=gateway, session_manager=sessions)

    def test_denied_authorization_fails_closed_without_backend_execution(self):
        sessions = SessionManager()
        context = sessions.create_session()
        adapter = self.make_adapter(sessions)

        result = adapter.execute_batch(
            batch=batch(context.run_id),
            tasks=(task(),),
            authorization=ExecutionAuthorization(False, "Gate C not approved"),
        )

        self.assertEqual(result[0].status, ExecutionStatus.DENIED)
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
                batch=batch(context.run_id, "worker-1"),
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


if __name__ == "__main__":
    unittest.main()
