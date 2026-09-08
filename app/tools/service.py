"""Capability-aware tool registry for M07.

This module is declarative by design: registering or resolving a tool never
executes it. Actual execution belongs to M08's Execution Gateway.
"""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Iterable

from .models import CapabilitySpec, RegistryValidation, ToolRegistration


class ToolRegistryError(ValueError):
    """Raised when a registry operation violates a runtime invariant."""


class ToolRegistry:
    """Thread-safe registry with fail-closed requirement resolution."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._capabilities: dict[str, CapabilitySpec] = {}
        self._tools: dict[str, ToolRegistration] = {}

    def register_capability(self, capability: CapabilitySpec) -> None:
        capability.validate()
        with self._lock:
            if capability.capability_id in self._capabilities:
                raise ToolRegistryError(
                    f"capability already registered: {capability.capability_id}"
                )
            self._capabilities[capability.capability_id] = capability

    def unregister_capability(self, capability_id: str) -> None:
        with self._lock:
            if capability_id not in self._capabilities:
                raise ToolRegistryError(f"unknown capability: {capability_id}")
            in_use = sorted(
                tool.tool_id
                for tool in self._tools.values()
                if capability_id in tool.capabilities
            )
            if in_use:
                raise ToolRegistryError(
                    f"capability is still required by registered tools: {in_use}"
                )
            del self._capabilities[capability_id]

    def get_capability(self, capability_id: str) -> CapabilitySpec:
        with self._lock:
            try:
                return self._capabilities[capability_id]
            except KeyError as exc:
                raise ToolRegistryError(f"unknown capability: {capability_id}") from exc

    def list_capabilities(self) -> tuple[CapabilitySpec, ...]:
        with self._lock:
            return tuple(self._capabilities[key] for key in sorted(self._capabilities))

    def register_tool(self, tool: ToolRegistration) -> None:
        tool.validate()
        with self._lock:
            if tool.tool_id in self._tools:
                raise ToolRegistryError(f"tool already registered: {tool.tool_id}")
            missing = sorted(set(tool.capabilities) - set(self._capabilities))
            if missing:
                raise ToolRegistryError(
                    f"tool {tool.tool_id} references unregistered capabilities: {missing}"
                )
            self._tools[tool.tool_id] = self._snapshot_tool(tool)

    def unregister_tool(self, tool_id: str) -> None:
        with self._lock:
            if tool_id not in self._tools:
                raise ToolRegistryError(f"unknown tool: {tool_id}")
            del self._tools[tool_id]

    def get_tool(self, tool_id: str, *, require_available: bool = False) -> ToolRegistration:
        with self._lock:
            try:
                tool = self._tools[tool_id]
            except KeyError as exc:
                raise ToolRegistryError(f"unknown tool: {tool_id}") from exc
            if require_available and not tool.available:
                raise ToolRegistryError(f"tool is unavailable: {tool_id}")
            return self._snapshot_tool(tool)

    def list_tools(self, *, available_only: bool = False) -> tuple[ToolRegistration, ...]:
        with self._lock:
            tools = (
                tool
                for tool in self._tools.values()
                if not available_only or tool.available
            )
            return tuple(
                self._snapshot_tool(tool)
                for tool in sorted(tools, key=lambda item: item.tool_id)
            )

    def tools_for_capabilities(
        self,
        capability_ids: Iterable[str],
        *,
        available_only: bool = True,
    ) -> tuple[ToolRegistration, ...]:
        requested = tuple(dict.fromkeys(capability_ids))
        with self._lock:
            missing = sorted(set(requested) - set(self._capabilities))
            if missing:
                raise ToolRegistryError(f"unknown capabilities: {missing}")
            matches = []
            requested_set = set(requested)
            for tool in self._tools.values():
                if available_only and not tool.available:
                    continue
                if requested_set.issubset(tool.capabilities):
                    matches.append(self._snapshot_tool(tool))
            return tuple(sorted(matches, key=lambda item: item.tool_id))

    def validate_requirements(
        self,
        *,
        required_tools: Iterable[str] = (),
        required_capabilities: Iterable[str] = (),
        available_only: bool = True,
    ) -> RegistryValidation:
        requested_tools = tuple(dict.fromkeys(required_tools))
        requested_capabilities = tuple(dict.fromkeys(required_capabilities))
        with self._lock:
            missing_capabilities = tuple(
                sorted(set(requested_capabilities) - set(self._capabilities))
            )
            missing_tools_list: list[str] = []
            resolved: list[ToolRegistration] = []
            for tool_id in requested_tools:
                tool = self._tools.get(tool_id)
                if tool is None or (available_only and not tool.available):
                    missing_tools_list.append(tool_id)
                else:
                    resolved.append(self._snapshot_tool(tool))
            return RegistryValidation(
                requested_tools=requested_tools,
                requested_capabilities=requested_capabilities,
                resolved_tools=tuple(resolved),
                missing_tools=tuple(missing_tools_list),
                missing_capabilities=missing_capabilities,
            )

    @staticmethod
    def _snapshot_tool(tool: ToolRegistration) -> ToolRegistration:
        """Return a detached registration so callers cannot mutate registry state."""
        return ToolRegistration(
            tool_id=tool.tool_id,
            name=tool.name,
            description=tool.description,
            handler=tool.handler,
            input_schema=deepcopy(dict(tool.input_schema)),
            output_schema=deepcopy(dict(tool.output_schema)),
            risk_level=tool.risk_level,
            requires_human_approval=tool.requires_human_approval,
            capabilities=tuple(tool.capabilities),
            available=tool.available,
            metadata=deepcopy(dict(tool.metadata)),
        )
