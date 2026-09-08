"""Contracts for registered tools and capabilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from app.core.contracts import RiskLevel


ToolHandler = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """Declarative capability a worker may require."""

    capability_id: str
    name: str
    description: str

    def validate(self) -> None:
        for field_name, value in (
            ("capability_id", self.capability_id),
            ("name", self.name),
            ("description", self.description),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    """Runtime registration for a concrete callable tool."""

    tool_id: str
    name: str
    description: str
    handler: ToolHandler
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_human_approval: bool = False
    capabilities: tuple[str, ...] = ()
    available: bool = True
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        for field_name, value in (
            ("tool_id", self.tool_id),
            ("name", self.name),
            ("description", self.description),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if not callable(self.handler):
            raise ValueError("handler must be callable")
        if self.risk_level == RiskLevel.HIGH and not self.requires_human_approval:
            raise ValueError("high-risk tools must require human approval")
        if any(not isinstance(capability, str) or not capability.strip() for capability in self.capabilities):
            raise ValueError("capabilities must contain non-empty strings")
