"""Provider-neutral LLM interface used by the runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """Single generation request independent of a specific LLM vendor."""

    model: str
    contents: Any
    system_instruction: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.model.strip():
            raise ValueError("model cannot be empty")
        if self.contents is None or contents_is_empty(self.contents):
            raise ValueError("contents cannot be empty")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_output_tokens is not None and self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be >= 1")


@dataclass(frozen=True, slots=True)
class GenerationResponse:
    """Normalized response returned to orchestration layers."""

    provider: str
    model: str
    text: str
    response_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None


class LLMProvider(Protocol):
    def generate(self, request: GenerationRequest) -> GenerationResponse: ...


def contents_is_empty(value: Any) -> bool:
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return len(value) == 0
    return False
