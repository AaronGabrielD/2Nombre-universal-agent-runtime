"""Worker runtime adapter for connecting M06 planning to M08 execution."""
from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.contracts import ExecutionRequest, ExecutionResult, TaskSpec
from app.execution.lease import ExecutionLeaseError, ExecutionLeaseService
from app.execution.models import ExecutionAuthorization
from app.execution.service import ExecutionGateway
from app.session.manager import SessionManager
from app.session.repository import SessionNotFoundError

from .models import DispatchBatch


class WorkerRuntimeError(RuntimeError):
    """Raised when a worker execution cannot safely proceed."""


@dataclass(frozen=True, slots=True)
class WorkerExecutionTask:
    task: TaskSpec
    language: str
    code: str
    timeout_seconds: int = 60
    needs_network: bool = False
    environment: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        self.task.validate()
        if not isinstance(self.language, str) or not self.language.strip():
            raise WorkerRuntimeError("language cannot be empty")
        if not isinstance(self.code, str) or not self.code.strip():
            raise WorkerRuntimeError("worker execution code cannot be empty")
        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds < 1
        ):
            raise WorkerRuntimeError("timeout_seconds must be a positive integer")
        if not isinstance(self.needs_network, bool):
            raise WorkerRuntimeError("needs_network must be boolean")
        if not isinstance(self.environment, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.environment.items()
        ):
            raise WorkerRuntimeError("environment must be a string-to-string mapping")


class WorkerRuntimeAdapter:
    """Execute run-scoped worker tasks through the central execution gateway."""

    def __init__(
        self,
        *,
        gateway: ExecutionGateway,
        session_manager: SessionManager,
        lease_service: ExecutionLeaseService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.gateway = gateway
        self.sessions = session_manager
        self.leases = lease_service or ExecutionLeaseService(session_manager=session_manager)
        self.settings = settings or getattr(gateway, "_settings", None) or get_settings()

    def execute_batch(
        self,
        *,
        batch: DispatchBatch,
        tasks: tuple[WorkerExecutionTask, ...],
        authorization: ExecutionAuthorization | None = None,
        authorization_by_worker: Mapping[str, ExecutionAuthorization] | None = None,
        backend_id: str | None = None,
        parallel: bool = False,
    ) -> tuple[ExecutionResult, ...]:
        self._validate_batch(batch=batch, tasks=tasks)
        validated_tasks = tuple(tasks)
        for item in validated_tasks:
            item.validate()
        authorizations = self._resolve_authorizations(
            batch=batch,
            tasks=validated_tasks,
            authorization=authorization,
            authorization_by_worker=authorization_by_worker,
        )
        if not parallel or len(validated_tasks) <= 1:
            return tuple(
                self._execute_one(
                    batch=batch,
                    item=item,
                    authorization=authorizations[item.task.worker_id],
                    backend_id=backend_id,
                )
                for item in validated_tasks
            )
        max_workers = min(len(validated_tasks), self.settings.max_workers)
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="uar-worker") as pool:
            futures = tuple(
                pool.submit(
                    self._execute_one,
                    batch=batch,
                    item=item,
                    authorization=authorizations[item.task.worker_id],
                    backend_id=backend_id,
                )
                for item in validated_tasks
            )
            return tuple(future.result() for future in futures)

    def _resolve_authorizations(
        self,
        *,
        batch: DispatchBatch,
        tasks: tuple[WorkerExecutionTask, ...],
        authorization: ExecutionAuthorization | None,
        authorization_by_worker: Mapping[str, ExecutionAuthorization] | None,
    ) -> dict[str, ExecutionAuthorization]:
        result: dict[str, ExecutionAuthorization] = {}
        worker_ids = {item.task.worker_id for item in tasks}
        if authorization_by_worker is not None:
            if set(authorization_by_worker) != worker_ids:
                raise WorkerRuntimeError(
                    "authorization_by_worker must contain exactly one grant per task worker"
                )
            for item in tasks:
                grant = authorization_by_worker[item.task.worker_id]
                if not isinstance(grant, ExecutionAuthorization):
                    raise WorkerRuntimeError("authorization_by_worker contains an invalid grant")
                if not grant.authorized or grant.worker_id != item.task.worker_id:
                    raise WorkerRuntimeError(
                        f"authorization is not valid for worker {item.task.worker_id}"
                    )
                if grant.run_id != batch.run_id:
                    raise WorkerRuntimeError("authorization run_id does not match batch")
                result[item.task.worker_id] = grant
            return result

        if authorization is None:
            raise WorkerRuntimeError("an explicit execution authorization is required")
        if not authorization.authorized or authorization.run_id != batch.run_id:
            raise WorkerRuntimeError("execution authorization does not match batch")
        if authorization.worker_id == "*":
            if self.settings.execution_backend != "test":
                raise WorkerRuntimeError(
                    "wildcard worker authorization is forbidden outside test mode"
                )
        elif authorization.worker_id not in worker_ids:
            raise WorkerRuntimeError("execution authorization does not match any task worker")
        for item in tasks:
            if authorization.worker_id not in {"*", item.task.worker_id}:
                raise WorkerRuntimeError(
                    f"worker-scoped execution requires authorization for {item.task.worker_id}"
                )
            result[item.task.worker_id] = authorization
        return result

    def _validate_batch(
        self,
        *,
        batch: DispatchBatch,
        tasks: tuple[WorkerExecutionTask, ...],
    ) -> None:
        if not isinstance(batch.run_id, str) or not batch.run_id.strip():
            raise WorkerRuntimeError("batch.run_id cannot be empty")
        try:
            self.sessions.get_context(batch.run_id)
        except SessionNotFoundError as exc:
            raise WorkerRuntimeError(f"unknown run_id: {batch.run_id}") from exc
        if any(worker.run_id != batch.run_id for worker in batch.workers):
            raise WorkerRuntimeError("all batch workers must belong to batch.run_id")
        worker_ids = {worker.worker_id for worker in batch.workers}
        task_workers = {item.task.worker_id for item in tasks}
        if task_workers - worker_ids:
            raise WorkerRuntimeError(
                f"tasks reference workers outside the batch: {sorted(task_workers - worker_ids)}"
            )
        if len(task_workers) != len(tasks):
            raise WorkerRuntimeError(
                "a dispatch batch cannot contain multiple tasks for the same worker"
            )

    def _execute_one(
        self,
        *,
        batch: DispatchBatch,
        item: WorkerExecutionTask,
        authorization: ExecutionAuthorization,
        backend_id: str | None,
    ) -> ExecutionResult:
        key = self.leases.idempotency_key(
            run_id=batch.run_id,
            worker_id=item.task.worker_id,
            task_id=item.task.task_id,
            language=item.language,
            code=item.code,
        )
        execution = ExecutionRequest(
            execution_id=f"exec-{uuid4().hex}",
            run_id=batch.run_id,
            worker_id=item.task.worker_id,
            language=item.language,
            code=item.code,
            timeout_seconds=item.timeout_seconds,
            needs_network=item.needs_network,
            environment=dict(item.environment),
            idempotency_key=key,
        )
        try:
            lease = self.leases.reserve(
                run_id=batch.run_id,
                worker_id=item.task.worker_id,
                task_id=item.task.task_id,
                idempotency_key=key,
                execution_id=execution.execution_id,
            )
        except ExecutionLeaseError as exc:
            raise WorkerRuntimeError(str(exc)) from exc

        if lease.status == "COMPLETED":
            for result in self.sessions.snapshot(batch.run_id).execution_results:
                if result.execution_id == lease.execution_id:
                    return result
            raise WorkerRuntimeError(
                f"completed execution lease {lease.lease_id} has no persisted result"
            )

        result = self.gateway.execute(
            execution,
            authorization=authorization,
            backend_id=backend_id,
        )
        self.sessions.add_execution_result(batch.run_id, result)
        try:
            self.leases.complete(run_id=batch.run_id, lease_id=lease.lease_id)
        except ExecutionLeaseError as exc:
            raise WorkerRuntimeError(str(exc)) from exc
        return result
