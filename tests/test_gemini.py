from __future__ import annotations

import unittest

from app.core.config import Settings
from app.llm.gemini import GeminiAdapter
from app.llm.interfaces import GenerationRequest


class GeminiAdapterTests(unittest.TestCase):
    def test_gemini_3_models_omit_temperature(self):
        request = GenerationRequest(
            model="gemini-3.5-flash",
            contents="hello",
            temperature=0.2,
            max_output_tokens=128,
        )
        config = GeminiAdapter._build_config_kwargs(request)
        self.assertNotIn("temperature", config)
        self.assertEqual(config["max_output_tokens"], 128)

    def test_gemini_3_8_model_is_detected(self):
        self.assertTrue(GeminiAdapter._is_gemini_3_model("gemini-3.8-flash"))

    def test_non_gemini_3_models_keep_provider_neutral_temperature(self):
        request = GenerationRequest(
            model="gemini-2.5-flash",
            contents="hello",
            temperature=0.2,
        )
        config = GeminiAdapter._build_config_kwargs(request)
        self.assertEqual(config["temperature"], 0.2)

    def test_model_detection_is_case_and_whitespace_tolerant(self):
        self.assertTrue(GeminiAdapter._is_gemini_3_model("  Gemini-3.5-Flash  "))
        self.assertFalse(GeminiAdapter._is_gemini_3_model("gemini-2.5-flash"))

    def test_settings_default_targets_supported_stable_gemini_3_model(self):
        settings = Settings(
            gemini_api_key=None,
            gemini_model_architect="gemini-3.5-flash",
            gemini_model_worker="gemini-3.5-flash",
            gemini_model_supervisor="gemini-3.5-flash",
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
        settings.validate()
        self.assertTrue(GeminiAdapter._is_gemini_3_model(settings.gemini_model_architect))


if __name__ == "__main__":
    unittest.main()
