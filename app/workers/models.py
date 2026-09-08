"""Provider-neutral worker runtime models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.contracts import TaskSpec, WorkerSpec


@dataclass(frozen=True, slots=True)
class WorkerInstance:
    """Runtime identity created from an architecture WorkerSpec."""

    worker_id: str
    role: str
    mission: str
    deliverables: tuple[str, ...]
    required_tools: tuple[str, ...]
    dependencies: tuple[str, ...]
    can_request_human_input: bool
    run_id: str

    @classmethod
    def from_spec(cls, *, run_id: str, spec: WorkerSpec) -> "WorkerInstance":
        spec.validate()
        return cls(
            worker_id=spec.worker_id,
            role=spec.role,
            mission=spec.mission,
            deliverables=spec.deliverables,
            required_tools=spec.required_tools,
            dependencies=spec.dependencies,
            can_request_human_input=spec.can_request_human_input,
            run_id=run_id,
        )


@dataclass(frozen=True, slots=True)
class DispatchBatch:
    """A batch of workers whose dependencies are already satisfied."""

    run_id: str
    workers: tuple[WorkerInstance, ...]
    tasks: tuple[TaskSpec, ...] = ()
    sequence: int = 0

    def worker_ids(self) -> tuple[str, ...]:
        return tuple(worker.worker_id for worker in self.workers)
