"""Worker creation and dependency-aware dispatch planning."""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.contracts import ArchitecturePlan, TaskSpec, WorkerSpec

from .models import DispatchBatch, WorkerInstance


class WorkerDispatchError(ValueError):
    """Raised when a worker plan cannot be safely dispatched."""


class WorkerFactory:
    """Convert validated WorkerSpec contracts into run-scoped worker instances."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def create_workers(
        self, *, run_id: str, plan: ArchitecturePlan
    ) -> tuple[WorkerInstance, ...]:
        if not run_id.strip():
            raise WorkerDispatchError("run_id cannot be empty")
        plan.validate(max_workers=self._settings.max_workers)
        workers = tuple(WorkerInstance.from_spec(run_id=run_id, spec=spec) for spec in plan.workers)
        if len(workers) > self._settings.max_workers:
            raise WorkerDispatchError("worker count exceeds configured maximum")
        return workers


class WorkerDispatcher:
    """Build dependency-safe dispatch batches without executing workers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def plan_batches(
        self,
        *,
        run_id: str,
        workers: Iterable[WorkerInstance],
        tasks: Iterable[TaskSpec] = (),
    ) -> tuple[DispatchBatch, ...]:
        workers_by_id = {worker.worker_id: worker for worker in workers}
        if not workers_by_id:
            raise WorkerDispatchError("at least one worker is required")
        if len(workers_by_id) > self._settings.max_workers:
            raise WorkerDispatchError("worker count exceeds configured maximum")
        if any(worker.run_id != run_id for worker in workers_by_id.values()):
            raise WorkerDispatchError("all workers must belong to run_id")

        for worker in workers_by_id.values():
            missing = set(worker.dependencies) - set(workers_by_id)
            if missing:
                raise WorkerDispatchError(
                    f"worker {worker.worker_id} has unknown dependencies: {sorted(missing)}"
                )

        task_map: dict[str, list[TaskSpec]] = defaultdict(list)
        for task in tasks:
            task.validate()
            if task.worker_id not in workers_by_id:
                raise WorkerDispatchError(
                    f"task {task.task_id} references unknown worker {task.worker_id}"
                )
            if task.worker_id != workers_by_id[task.worker_id].worker_id:
                raise WorkerDispatchError(f"task {task.task_id} has inconsistent worker_id")
            task_map[task.worker_id].append(task)

        indegree = {worker_id: len(worker.dependencies) for worker_id, worker in workers_by_id.items()}
        dependents: dict[str, list[str]] = defaultdict(list)
        for worker in workers_by_id.values():
            for dependency in worker.dependencies:
                dependents[dependency].append(worker.worker_id)

        ready = deque(sorted(worker_id for worker_id, degree in indegree.items() if degree == 0))
        batches: list[DispatchBatch] = []
        dispatched: set[str] = set()
        sequence = 0

        while ready:
            current_ids = tuple(ready.popleft() for _ in range(len(ready)))
            current_workers = tuple(workers_by_id[item] for item in current_ids)
            current_tasks = tuple(
                task
                for worker_id in current_ids
                for task in task_map.get(worker_id, ())
            )
            batches.append(
                DispatchBatch(
                    run_id=run_id,
                    workers=current_workers,
                    tasks=current_tasks,
                    sequence=sequence,
                )
            )
            dispatched.update(current_ids)
            sequence += 1

            newly_ready: list[str] = []
            for completed_id in current_ids:
                for dependent_id in dependents[completed_id]:
                    indegree[dependent_id] -= 1
                    if indegree[dependent_id] == 0:
                        newly_ready.append(dependent_id)
            for worker_id in sorted(newly_ready):
                ready.append(worker_id)

        if len(dispatched) != len(workers_by_id):
            unresolved = sorted(set(workers_by_id) - dispatched)
            raise WorkerDispatchError(
                f"worker dependency graph contains a cycle or unresolved dependency: {unresolved}"
            )
        return tuple(batches)

    @staticmethod
    def build_task(
        *,
        worker_id: str,
        description: str,
        expected_output: str,
        required_tools: tuple[str, ...] = (),
        task_id: str | None = None,
    ) -> TaskSpec:
        """Create a validated task contract without executing it."""
        task = TaskSpec(
            task_id=task_id or f"task-{uuid4().hex}",
            worker_id=worker_id,
            description=description,
            expected_output=expected_output,
            required_tools=required_tools,
        )
        task.validate()
        return task
