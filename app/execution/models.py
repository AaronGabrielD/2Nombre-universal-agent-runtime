"""M08 execution gateway contracts."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionBackendInfo:
    """Describes an execution backend without coupling the core to it."""

    backend_id: str
    name: str
    available: bool = True

    def validate(self) -> None:
        if not self.backend_id.strip():
            raise ValueError("backend_id cannot be empty")
        if not self.name.strip():
            raise ValueError("name cannot be empty")


@dataclass(frozen=True, slots=True)
class ExecutionAuthorization:
    """Explicit authorization supplied by an upstream policy/approval layer."""

    authorized: bool
    reason: str = ""
    gate_id: str | None = None

    def validate(self) -> None:
        if not self.authorized and not self.reason.strip():
            raise ValueError("denied authorization requires a reason")
