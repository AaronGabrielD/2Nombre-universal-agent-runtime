import unittest

from app.agents.crewai_adapter import CrewAIWorkerAdapter, CrewAIWorkerAdapterError
from app.core.config import Settings
from app.core.contracts import TaskSpec
from app.workers.models import WorkerInstance


class FakeResult:
    def __init__(self, raw: str):
        self.raw = raw


class FakeCrew:
    def __init__(self, raw: str):
        self.raw = raw
        self.inputs = None

    def kickoff(self, *, inputs=None):
        self.inputs = inputs
        return FakeResult(self.raw)


def settings():
    return Settings(
        gemini_api_key="test-key",
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


def worker():
    return WorkerInstance(
        worker_id="worker-1",
        role="builder",
        mission="build the requested artifact",
        deliverables=("artifact",),
        required_tools=(),
        dependencies=(),
        can_request_human_input=True,
        run_id="run-1",
    )


def task(worker_id="worker-1"):
    return TaskSpec(
        task_id="task-1",
        worker_id=worker_id,
        description="produce executable code",
        expected_output="a working script",
    )


class CrewAIAdapterTests(unittest.TestCase):
    def test_builds_provider_neutral_execution_plan(self):
        crew = FakeCrew(
            '{"summary":"generated","language":"python","code":"print(42)",'
            '"timeout_seconds":30,"needs_network":false,"environment":{}}'
        )
        adapter = CrewAIWorkerAdapter(settings(), crew_factory=lambda *_: crew)

        plan = adapter.build_execution_plan(
            worker=worker(),
            task=task(),
            context={"objective": "test"},
        )

        self.assertEqual(plan.worker_id, "worker-1")
        self.assertEqual(plan.task_id, "task-1")
        self.assertEqual(plan.execution_task.code, "print(42)")
        self.assertEqual(crew.inputs, {"objective": "test"})

    def test_rejects_task_from_another_worker(self):
        adapter = CrewAIWorkerAdapter(settings(), crew_factory=lambda *_: FakeCrew("{}"))
        with self.assertRaises(CrewAIWorkerAdapterError):
            adapter.build_execution_plan(worker=worker(), task=task("worker-2"))

    def test_rejects_invalid_json(self):
        adapter = CrewAIWorkerAdapter(settings(), crew_factory=lambda *_: FakeCrew("not-json"))
        with self.assertRaises(CrewAIWorkerAdapterError):
            adapter.build_execution_plan(worker=worker(), task=task())

    def test_rejects_empty_generated_code(self):
        crew = FakeCrew(
            '{"summary":"generated","language":"python","code":"   ",'
            '"timeout_seconds":30,"needs_network":false,"environment":{}}'
        )
        adapter = CrewAIWorkerAdapter(settings(), crew_factory=lambda *_: crew)
        with self.assertRaises(CrewAIWorkerAdapterError):
            adapter.build_execution_plan(worker=worker(), task=task())

    def test_crew_failure_is_wrapped(self):
        class FailingCrew:
            def kickoff(self, *, inputs=None):
                raise RuntimeError("provider down")

        adapter = CrewAIWorkerAdapter(settings(), crew_factory=lambda *_: FailingCrew())
        with self.assertRaises(CrewAIWorkerAdapterError) as ctx:
            adapter.build_execution_plan(worker=worker(), task=task())
        self.assertIn("provider down", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
