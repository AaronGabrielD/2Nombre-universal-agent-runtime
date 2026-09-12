"""Provider-neutral deployment contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath


@dataclass(frozen=True, slots=True)
class DeploymentEnvironment:
    key: str
    required: bool = True
    secret: bool = False
    value: str | None = field(default=None, repr=False)

    def validate(self) -> None:
        if not isinstance(self.key, str) or not self.key or not self.key.replace("_", "A").isalnum() or self.key[0].isdigit():
            raise ValueError(f"invalid environment key: {self.key!r}")
        if not isinstance(self.required, bool) or not isinstance(self.secret, bool):
            raise ValueError("required and secret must be boolean")
        if self.value is not None and not isinstance(self.value, str):
            raise ValueError("environment value must be a string or None")
        if self.secret and self.value is not None and not self.value:
            raise ValueError(f"secret environment value for {self.key} cannot be empty")


@dataclass(frozen=True, slots=True)
class DeploymentSpec:
    name: str
    command: tuple[str, ...]
    port: int
    health_path: str = "/health"
    environment: tuple[DeploymentEnvironment, ...] = ()
    working_directory: str = "."

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or not self.name.replace("-", "A").replace("_", "A").isalnum() or self.name[0].isdigit():
            raise ValueError("deployment name must be a simple identifier")
        if not isinstance(self.command, (tuple, list)) or not self.command or any(not isinstance(part, str) or not part.strip() for part in self.command):
            raise ValueError("deployment command cannot be empty")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("deployment port must be between 1 and 65535")
        if not isinstance(self.health_path, str) or not self.health_path.startswith("/") or "\n" in self.health_path or "\r" in self.health_path or "\"" in self.health_path or "'" in self.health_path or "\\" in self.health_path:
            raise ValueError("health_path contains unsafe characters")
        if not isinstance(self.working_directory, str) or not self.working_directory.strip() or "\n" in self.working_directory or "\r" in self.working_directory:
            raise ValueError("working_directory contains invalid characters")
        seen: set[str] = set()
        for entry in self.environment:
            entry.validate()
            if entry.key in seen:
                raise ValueError(f"duplicate environment key: {entry.key}")
            seen.add(entry.key)


@dataclass(frozen=True, slots=True)
class DeploymentRender:
    provider: str
    files: tuple[tuple[str, str], ...]
    instructions: tuple[str, ...] = ()
