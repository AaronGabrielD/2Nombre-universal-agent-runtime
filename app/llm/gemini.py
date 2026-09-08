"""Gemini implementation of the provider-neutral LLM interface."""
from __future__ import annotations

import time
from typing import Any, Callable

from app.core.config import Settings, get_settings
from app.core.exceptions import RuntimeErrorBase

from .interfaces import GenerationRequest, GenerationResponse


class GeminiAdapterError(RuntimeErrorBase):
    """Expected failure while communicating with Gemini."""


class GeminiAdapter:
    """Lazy, bounded adapter around the official google-genai SDK."""

    provider_name = "gemini"
    _HTTP_TIMEOUT_MS = 120_000
    _MAX_ATTEMPTS = 3

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._sleep = sleep

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:
                raise GeminiAdapterError(
                    "google-genai is required. Install the runtime dependencies first."
                ) from exc
            api_key = self.settings.require_gemini_key()
            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=self._HTTP_TIMEOUT_MS),
            )
        return self._client

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        request.validate()

        last_error: Exception | None = None
        for attempt in range(self._MAX_ATTEMPTS):
            try:
                config_kwargs: dict[str, Any] = {}
                if request.system_instruction:
                    config_kwargs["system_instruction"] = request.system_instruction
                if request.temperature is not None:
                    config_kwargs["temperature"] = request.temperature
                if request.max_output_tokens is not None:
                    config_kwargs["max_output_tokens"] = request.max_output_tokens

                config: Any | None = None
                if config_kwargs:
                    from google.genai import types
                    config = types.GenerateContentConfig(**config_kwargs)

                response = self.client.models.generate_content(
                    model=request.model,
                    contents=request.contents,
                    config=config,
                )
                return self._normalize_response(request, response)
            except Exception as exc:  # SDK exception types vary across releases.
                last_error = exc
                if not self._is_retryable(exc) or attempt == self._MAX_ATTEMPTS - 1:
                    break
                self._sleep(2**attempt)

        raise GeminiAdapterError(
            f"Gemini generation failed after {self._MAX_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def _normalize_response(
        self, request: GenerationRequest, response: Any
    ) -> GenerationResponse:
        text = getattr(response, "text", None)
        if text is None:
            raise GeminiAdapterError("Gemini returned no textual response")

        usage: dict[str, int] = {}
        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata is not None:
            for source_name, output_name in (
                ("prompt_token_count", "input_tokens"),
                ("candidates_token_count", "output_tokens"),
                ("total_token_count", "total_tokens"),
            ):
                value = getattr(usage_metadata, source_name, None)
                if isinstance(value, int):
                    usage[output_name] = value

        response_id = getattr(response, "response_id", None)
        return GenerationResponse(
            provider=self.provider_name,
            model=request.model,
            text=text,
            response_id=response_id,
            usage=usage,
            raw=response,
        )

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        name = type(exc).__name__.lower()
        message = str(exc).lower()
        retry_markers = (
            "429",
            "resourceexhausted",
            "ratelimit",
            "toomanyrequests",
            "503",
            "unavailable",
            "deadline",
            "timeout",
            "temporarily",
        )
        return any(marker in name or marker in message for marker in retry_markers)
