import unittest
from dataclasses import replace
from types import SimpleNamespace

from app.core.config import get_settings
from app.llm.gemini import GeminiAdapter, GeminiAdapterError
from app.llm.interfaces import GenerationRequest


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, models):
        self.models = models


class GeminiAdapterTests(unittest.TestCase):
    def test_generation_is_normalized(self):
        usage = SimpleNamespace(
            prompt_token_count=10,
            candidates_token_count=5,
            total_token_count=15,
        )
        response = SimpleNamespace(text="hello", response_id="resp-1", usage_metadata=usage)
        models = FakeModels(response=response)
        settings = get_settings(reload=True)
        adapter = GeminiAdapter(settings=replace(settings, gemini_api_key="test-key"), client=FakeClient(models))

        result = adapter.generate(GenerationRequest(model="gemini-3.5-flash", contents="Say hello"))

        self.assertEqual(result.provider, "gemini")
        self.assertEqual(result.text, "hello")
        self.assertEqual(result.response_id, "resp-1")
        self.assertEqual(result.usage["input_tokens"], 10)
        self.assertEqual(models.calls[0]["model"], "gemini-3.5-flash")

    def test_empty_request_is_rejected_before_provider_call(self):
        models = FakeModels(response=SimpleNamespace(text="unused"))
        adapter = GeminiAdapter(client=FakeClient(models))
        with self.assertRaises(ValueError):
            adapter.generate(GenerationRequest(model="gemini-3.5-flash", contents="  "))
        self.assertEqual(models.calls, [])

    def test_missing_api_key_is_not_needed_when_client_is_injected(self):
        settings = get_settings(reload=True)
        adapter = GeminiAdapter(settings=replace(settings, gemini_api_key=None), client=FakeClient(FakeModels(SimpleNamespace(text="ok"))))
        result = adapter.generate(GenerationRequest(model="gemini-3.5-flash", contents="test"))
        self.assertEqual(result.text, "ok")

    def test_transient_error_retries(self):
        class TemporaryUnavailable(Exception):
            pass

        models = FakeModels(error=TemporaryUnavailable("503 unavailable"))
        sleeps = []
        settings = get_settings(reload=True)
        adapter = GeminiAdapter(
            settings=replace(settings, gemini_api_key="test-key"),
            client=FakeClient(models),
            sleep=sleeps.append,
        )
        with self.assertRaises(GeminiAdapterError):
            adapter.generate(GenerationRequest(model="gemini-3.5-flash", contents="test"))
        self.assertEqual(len(models.calls), 3)
        self.assertEqual(sleeps, [1, 2])

    def test_permanent_error_does_not_retry(self):
        models = FakeModels(error=ValueError("bad request"))
        sleeps = []
        adapter = GeminiAdapter(client=FakeClient(models), sleep=sleeps.append)
        with self.assertRaises(GeminiAdapterError):
            adapter.generate(GenerationRequest(model="gemini-3.5-flash", contents="test"))
        self.assertEqual(len(models.calls), 1)
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
