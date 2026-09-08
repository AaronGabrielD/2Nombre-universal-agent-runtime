"""Worker runtime adapter for connecting M06 planning to M08 execution.

The adapter executes only pre-built worker tasks. It does not decide whether a
run may execute; upstream orchestration must provide explicit authorization to
M08 for every execution request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from app.core.contracts import ExecutionRequest, ExecutionResult, TaskSpec
from app.execution.models import ExecutionAuthorization
from app.execution.service import ExecutionGateway
from app.session.manager import SessionManager

from .models import DispatchBatch


class WorkerRuntimeError(RuntimeError):
    """Raised when a worker batch cannot be safely translated to execution."""


@dataclass(frozen=True, slots=True)
class WorkerExecutionTask:
    """Executable representation of one planned task.

    Code must be supplied by an upstream worker implementation. The runtime
    adapter does not ask an LLM to generate code and does not invent tasks.
    """

    task: TaskSpec
    language: str
    code: str
    timeout_seconds: int = 60
    needs_network: bool = False
    environment: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        self.task.validate()
        if not self.language.strip():
            raise WorkerRuntimeError("language cannot be empty")
        if not self.code.strip():
            raise WorkerRuntimeError("worker execution code cannot be empty")
        if not isinstance(self.timeout_seconds, int) or isinstance(self.timeout_seconds, bool):
            raise WorkerRuntimeError("timeout_seconds must be an integer")
        if self.timeout_seconds < 1:
            raise WorkerRuntimeError("timeout_seconds must be positive")
        if not isinstance(self.needs_network, bool):
            raise WorkerRuntimeError("needs_network must be boolean")
        if not isinstance(self.environment, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.environment.items()
        ):
            raise WorkerRuntimeError("environment must be a string-to-string mapping")


class WorkerRuntimeAdapter:
    """Execute a worker batch through M08 and persist results in M01."""

    def __init__(
        self,
        *,
        gateway: ExecutionGateway,
        session_manager: SessionManager,
    ) -> None:
        self.gateway = gateway
        self.sessions = session_manager

    def execute_batch(
        self,
        *,
        batch: DispatchBatch,
        tasks: tuple[WorkerExecutionTask, ...],
        authorization: ExecutionAuthorization,
        backend_id: str | None = None,
    ) -> tuple[ExecutionResult, ...]:
        """Execute a batch deterministically and record each result in M01.

        Only tasks whose worker belongs to the supplied batch and run may pass.
        The gateway remains the sole execution boundary.
        """
        if not batch.run_id.strip():
            raise WorkerRuntimeError("batch.run_id cannot be empty")
        if any(worker.run_id != batch.run_id for worker in batch.workers):
            raise WorkerRuntimeError("all batch workers must belong to batch.run_id")

        worker_ids = {worker.worker_id for worker in batch.workers}
        task_workers = {item.task.worker_id for item in tasks}
        unknown = task_workers - worker_ids
        if unknown:
            raise WorkerRuntimeError(f"tasks reference workers outside the batch: {sorted(unknown)}")

        results: list[ExecutionResult] = []
        for item in tasks:
            item.validate()
            execution = ExecutionRequest(
                execution_id=f"exec-{uuid4().hex}",
                run_id=batch.run_id,
                worker_id=item.task.worker_id,
                language=item.language,
                code=item.code,
                timeout_seconds=item.timeout_seconds,
                needs_network=item.needs_network,
                environment=dict(item.environment),
            )
            result = self.gateway.execute(
                execution,
                authorization=authorization,
                backend_id=backend_id,
            )
            self.sessions.add_execution_result(batch.run_id, result)
            results.append(result)
        return tuple(results)
