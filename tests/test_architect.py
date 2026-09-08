import unittest

from app.architect.models import ArchitectureInput
from app.architect.service import ArchitectPlanningError, UniversalArchitect
from app.core.config import Settings
from app.llm.interfaces import GenerationResponse


class FakeProvider:
    def __init__(self, text: str):
        self.text = text
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return GenerationResponse(provider="fake", model=request.model, text=self.text)


def settings(**overrides):
    values = dict(
        gemini_api_key=None,
        gemini_model_architect="test-model",
        gemini_model_worker="test-worker",
        gemini_model_supervisor="test-supervisor",
        gemini_temperature=0.8,
        max_workers=4,
        min_workers=3,
        default_execution_timeout_seconds=60,
        max_uploads_per_message=20,
        max_upload_size_mb=100,
        execution_backend="colab",
        execution_gateway_url=None,
        execution_gateway_token=None,
    )
    values.update(overrides)
    return Settings(**values)


class ArchitectTests(unittest.TestCase):
    def test_builds_valid_plan(self):
        provider = FakeProvider(
            '{"plan_id":"p1","objective":"Build X",'
            '"assumptions":["A"],"constraints":["C"],'
            '"acceptance_criteria":["AC1"],"risks":["R"],'
            '"required_capabilities":["analysis"],"workers":['
            '{"worker_id":"w1","role":"research","mission":"Research",'
            '"deliverables":["notes"],"required_tools":["search"],"dependencies":[],"can_request_human_input":true},'
            '{"worker_id":"w2","role":"builder","mission":"Build",'
            '"deliverables":["artifact"],"required_tools":[],"dependencies":["w1"],"can_request_human_input":true}]}'
        )
        architect = UniversalArchitect(provider, settings())

        plan = architect.build_plan(ArchitectureInput(objective="Build X"))

        self.assertEqual(plan.plan_id, "p1")
        self.assertEqual(len(plan.workers), 2)
        self.assertEqual(plan.workers[1].dependencies, ("w1",))
        self.assertEqual(provider.requests[0].model, "test-model")
        self.assertEqual(provider.requests[0].temperature, 0.2)

    def test_accepts_markdown_fenced_json(self):
        provider = FakeProvider(
            '```json\n{"plan_id":"p","objective":"X","workers":['
            '{"worker_id":"w","role":"r","mission":"m"}]}\n```'
        )
        plan = UniversalArchitect(provider, settings()).build_plan(ArchitectureInput("X"))
        self.assertEqual(plan.plan_id, "p")

    def test_rejects_invalid_json(self):
        provider = FakeProvider("not json")
        with self.assertRaises(ArchitectPlanningError):
            UniversalArchitect(provider, settings()).build_plan(ArchitectureInput("X"))

    def test_rejects_unknown_worker_dependency(self):
        provider = FakeProvider(
            '{"plan_id":"p","objective":"X","workers":['
            '{"worker_id":"w","role":"r","mission":"m","dependencies":["missing"]}]}'
        )
        with self.assertRaises(ArchitectPlanningError):
            UniversalArchitect(provider, settings()).build_plan(ArchitectureInput("X"))

    def test_rejects_worker_limit(self):
        workers = ",".join(
            '{"worker_id":"w%d","role":"r","mission":"m"}' % i for i in range(5)
        )
        provider = FakeProvider('{"plan_id":"p","objective":"X","workers":[' + workers + ']}')
        with self.assertRaises(ArchitectPlanningError):
            UniversalArchitect(provider, settings(max_workers=4)).build_plan(ArchitectureInput("X"))

    def test_empty_objective_is_rejected_before_provider_call(self):
        provider = FakeProvider("{}")
        with self.assertRaises(ValueError):
            UniversalArchitect(provider, settings()).build_plan(ArchitectureInput("  "))
        self.assertEqual(provider.requests, [])


if __name__ == "__main__":
    unittest.main()
