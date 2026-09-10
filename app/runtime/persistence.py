"""Persistence selection for the runtime composition root."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.session.json_repository import JsonFileSessionRepository
from app.session.repository import InMemorySessionRepository, SQLiteSessionRepository, SessionRepository


class RuntimePersistenceError(ValueError):
    """Raised when runtime persistence configuration is invalid."""


@dataclass(frozen=True, slots=True)
class RuntimePersistenceConfig:
    backend: str = "memory"
    location: str | None = None

    def validate(self) -> None:
        if self.backend not in {"memory", "json", "sqlite"}:
            raise RuntimePersistenceError("backend must be 'memory', 'json', or 'sqlite'")
        if self.backend != "memory" and (self.location is None or not self.location.strip()):
            raise RuntimePersistenceError(f"location is required for {self.backend} persistence")


def persistence_config_from_environment() -> RuntimePersistenceConfig:
    backend = os.getenv("UAR_SESSION_REPOSITORY", "memory").strip().lower()
    if backend == "json":
        location = os.getenv("UAR_SESSION_REPOSITORY_PATH", "runtime_sessions")
    elif backend == "sqlite":
        location = os.getenv("UAR_SESSION_REPOSITORY_PATH", "runtime_sessions.db")
    else:
        location = None
    config = RuntimePersistenceConfig(backend=backend, location=location)
    config.validate()
    return config


def build_session_repository(config: RuntimePersistenceConfig | None = None) -> SessionRepository:
    config = config or persistence_config_from_environment()
    config.validate()
    if config.backend == "memory":
        return InMemorySessionRepository()
    if config.backend == "json":
        return JsonFileSessionRepository(str(Path(config.location).expanduser()))
    return SQLiteSessionRepository(str(Path(config.location).expanduser()))
