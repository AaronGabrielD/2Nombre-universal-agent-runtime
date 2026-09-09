"""Provider-neutral deployment contracts."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DeploymentEnvironment:
    """Validated environment entry without storing secret material in plans."""

    key: str
    required: bool = True
    secret: bool = False
    value: str | None = field(default=None, repr=False)

    def validate(self) -> None:
        if not self.key or not self.key.replace("_", "A").isalnum() or self.key[0].isdigit():
            raise ValueError(f"invalid environment key: {self.key!r}")
        if self.secret and self.value is not None and not self.value:
            raise ValueError(f"secret environment value for {self.key} cannot be empty")


@dataclass(frozen=True, slots=True)
class DeploymentSpec:
    """Portable application deployment specification."""

    name: str
    command: tuple[str, ...]
    port: int
    health_path: str = "/health"
    environment: tuple[DeploymentEnvironment, ...] = ()
    working_directory: str = "."

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("deployment name cannot be empty")
        if not self.command or any(not part.strip() for part in self.command):
            raise ValueError("deployment command cannot be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("deployment port must be between 1 and 65535")
        if not self.health_path.startswith("/"):
            raise ValueError("health_path must start with '/'")
        if not self.working_directory.strip():
            raise ValueError("working_directory cannot be empty")
        seen: set[str] = set()
        for entry in self.environment:
            entry.validate()
            if entry.key in seen:
                raise ValueError(f"duplicate environment key: {entry.key}")
            seen.add(entry.key)


@dataclass(frozen=True, slots=True)
class DeploymentRender:
    """Provider-specific rendered output produced by an adapter."""

    provider: str
    files: tuple[tuple[str, str], ...]
    instructions: tuple[str, ...] = ()
