"""Declarative contracts for the M07 capability and tool registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping

from app.core.contracts import RiskLevel


ToolHandler = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """A named capability that the runtime can explicitly expose."""

    capability_id: str
    name: str
    description: str

    def validate(self) -> None:
        for field_name in ("capability_id", "name", "description"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    """Metadata required to make a concrete tool discoverable by the runtime.

    The registry stores a handler reference but never invokes it. Execution is
    intentionally delegated to M08 (Execution Gateway).
    """

    tool_id: str
    name: str
    description: str
    handler: ToolHandler
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_human_approval: bool = False
    capabilities: tuple[str, ...] = ()
    available: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for field_name in ("tool_id", "name", "description"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if not callable(self.handler):
            raise ValueError("handler must be callable")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must not contain duplicates")
        if any(not isinstance(item, str) or not item.strip() for item in self.capabilities):
            raise ValueError("capability identifiers cannot be empty")
        if self.risk_level == RiskLevel.HIGH and not self.requires_human_approval:
            raise ValueError("high-risk tools must require human approval")


@dataclass(frozen=True, slots=True)
class RegistryValidation:
    """Result of resolving requested tools/capabilities against the registry."""

    requested_tools: tuple[str, ...]
    requested_capabilities: tuple[str, ...]
    resolved_tools: tuple[ToolRegistration, ...]
    missing_tools: tuple[str, ...]
    missing_capabilities: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.missing_tools and not self.missing_capabilities


class ToolResolutionStatus(str, Enum):
    """Classification used when a caller resolves a concrete tool."""

    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
