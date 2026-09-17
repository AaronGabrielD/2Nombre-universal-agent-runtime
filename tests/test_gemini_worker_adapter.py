import unittest

from app.agents.gemini_worker_adapter import GeminiWorkerAdapter, GeminiWorkerAdapterError
from app.core.config import Settings
from app.core.contracts import TaskSpec
from app.llm.interfaces import GenerationResponse
from app.workers.models import WorkerInstance


class FakeProvider:
    def __init__(self, text: str):
        self.text = text
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return GenerationResponse(provider="fake", model=request.model, text=self.text)


def settings():
    return Settings(
        gemini_api_key="test-key",
        gemini_model_architect="architect",
        gemini_model_worker="worker",
        gemini_model_supervisor="supervisor",
        gemini_temperature=0.8,
        max_workers=4,
        min_workers=1,
        default_execution_timeout_seconds=60,
        max_uploads_per_message=20,
        max_upload_size_mb=100,
        execution_backend="test",
        execution_gateway_url=None,
        execution_gateway_token=None,
        execution_authorization_secret="test-execution-authorization-secret-1234567890",
    )


def worker():
    return WorkerInstance(
        worker_id="worker-1",
        role="builder",
        mission="build a small program",
        deliverables=("program",),
        required_tools=(),
        dependencies=(),
        can_request_human_input=True,
        run_id="run-1",
    )


def task():
    return TaskSpec(
        task_id="task-1",
        worker_id="worker-1",
        description="Print a greeting",
        expected_output="A greeting on stdout",
    )


class GeminiWorkerAdapterTests(unittest.TestCase):
    def test_builds_execution_plan_without_crewai(self):
        provider = FakeProvider(
            '{"summary":"hello","language":"python","code":"print(\\"hello\\")",'
            '"timeout_seconds":12,"needs_network":false,"environment":{}}'
        )
        adapter = GeminiWorkerAdapter(settings(), provider=provider)

        result = adapter.build_execution_plan(worker=worker(), task=task())

        self.assertEqual(result.worker_id, "worker-1")
        self.assertEqual(result.execution_task.language, "python")
        self.assertEqual(result.execution_task.timeout_seconds, 12)
        self.assertEqual(provider.requests[0].model, "worker")

    def test_rejects_invalid_worker_json(self):
        provider = FakeProvider("not json")
        adapter = GeminiWorkerAdapter(settings(), provider=provider)
        with self.assertRaises(GeminiWorkerAdapterError):
            adapter.build_execution_plan(worker=worker(), task=task())


if __name__ == "__main__":
    unittest.main()
