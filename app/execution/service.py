"""Backend-neutral execution gateway for M08.

The gateway validates requests, enforces explicit authorization, selects a
registered backend, and delegates execution. It never knows whether the
backend is local, Colab, Docker, or a remote service.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from time import monotonic
from typing import Iterable

from app.core.contracts import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.core.config import Settings, get_settings

from .models import ExecutionAuthorization, ExecutionBackendInfo


class ExecutionGatewayError(RuntimeError):
    """Raised when execution cannot be safely delegated."""


class ExecutionBackend(ABC):
    """Minimal backend contract required by the execution gateway."""

    @property
    @abstractmethod
    def info(self) -> ExecutionBackendInfo:
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        raise NotImplementedError


class ExecutionGateway:
    """Central execution boundary with explicit authorization and backend selection."""

    def __init__(
        self,
        *,
        backends: Iterable[ExecutionBackend] = (),
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._backends = {backend.info.backend_id: backend for backend in backends}
        if len(self._backends) != len(tuple(backends)):
            raise ExecutionGatewayError("backend IDs must be unique")

    def list_backends(self, *, available_only: bool = False) -> tuple[ExecutionBackendInfo, ...]:
        values = (backend.info for backend in self._backends.values())
        if available_only:
            values = (info for info in values if info.available)
        return tuple(sorted(values, key=lambda item: item.backend_id))

    def execute(
        self,
        request: ExecutionRequest,
        *,
        authorization: ExecutionAuthorization | None = None,
        backend_id: str | None = None,
    ) -> ExecutionResult:
        request.validate(max_timeout_seconds=3600)
        auth = authorization or ExecutionAuthorization(False, "execution requires explicit authorization")
        try:
            auth.validate()
        except ValueError as exc:
            raise ExecutionGatewayError(str(exc)) from exc
        if not auth.authorized:
            return ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.DENIED,
                exit_code=None,
                stdout="",
                stderr=auth.reason,
                duration_ms=0,
                backend=backend_id or self._settings.execution_backend,
            )

        selected_id = backend_id or self._settings.execution_backend
        backend = self._backends.get(selected_id)
        if backend is None:
            return ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.UNAVAILABLE,
                exit_code=None,
                stdout="",
                stderr=f"execution backend is not registered: {selected_id}",
                duration_ms=0,
                backend=selected_id,
            )
        if not backend.info.available:
            return ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.UNAVAILABLE,
                exit_code=None,
                stdout="",
                stderr=f"execution backend is unavailable: {selected_id}",
                duration_ms=0,
                backend=selected_id,
            )

        started = monotonic()
        try:
            result = backend.execute(request)
        except TimeoutError as exc:
            return ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.TIMEOUT,
                exit_code=None,
                stdout="",
                stderr=str(exc) or "execution timed out",
                duration_ms=_elapsed_ms(started),
                backend=selected_id,
            )
        except Exception as exc:
            return ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.ERROR,
                exit_code=None,
                stdout="",
                stderr=f"{type(exc).__name__}: {exc}",
                duration_ms=_elapsed_ms(started),
                backend=selected_id,
            )

        if result.execution_id != request.execution_id:
            raise ExecutionGatewayError("backend returned an inconsistent execution_id")
        return result


def _elapsed_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))
