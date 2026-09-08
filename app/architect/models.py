"""Input model for the provider-neutral Universal Architect."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ArchitectureInput:
    """Normalized context given to the architect before planning."""

    objective: str
    inputs: tuple[dict[str, Any], ...] = ()
    context: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.objective.strip():
            raise ValueError("objective cannot be empty")

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "objective": self.objective.strip(),
            "inputs": list(self.inputs),
            "context": self.context,
        }
