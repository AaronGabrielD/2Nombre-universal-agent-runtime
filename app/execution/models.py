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
        if not isinstance(self.backend_id, str) or not self.backend_id.strip():
            raise ValueError("backend_id cannot be empty")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name cannot be empty")
        if not isinstance(self.available, bool):
            raise ValueError("available must be boolean")


@dataclass(frozen=True, slots=True)
class ExecutionAuthorization:
    """Scoped execution grant produced by the authorization boundary.

    A boolean alone is deliberately insufficient: an execution grant is bound
    to the run, worker, backend and network requirement it authorizes.
    """

    authorized: bool
    reason: str = ""
    gate_id: str | None = None
    run_id: str | None = None
    worker_id: str | None = None
    backend_id: str | None = None
    network_allowed: bool = False

    def validate(self) -> None:
        if not isinstance(self.authorized, bool):
            raise ValueError("authorized must be boolean")
        if not isinstance(self.reason, str):
            raise ValueError("reason must be a string")
        if not self.authorized and not self.reason.strip():
            raise ValueError("denied authorization requires a reason")
        if self.authorized:
            for name, value in (("run_id", self.run_id), ("worker_id", self.worker_id), ("backend_id", self.backend_id)):
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"authorized execution requires {name}")
        if self.gate_id is not None and (not isinstance(self.gate_id, str) or not self.gate_id.strip()):
            raise ValueError("gate_id must be a non-empty string when supplied")
        if not isinstance(self.network_allowed, bool):
            raise ValueError("network_allowed must be boolean")
