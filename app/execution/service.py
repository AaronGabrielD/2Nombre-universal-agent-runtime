"""Backend-neutral execution gateway for M08."""
from __future__ import annotations

from abc import ABC, abstractmethod
from time import monotonic
from typing import Iterable

from app.core.config import Settings, get_settings
from app.core.contracts import ExecutionRequest, ExecutionResult, ExecutionStatus

from .models import ExecutionAuthorization, ExecutionBackendInfo


class ExecutionGatewayError(RuntimeError):
    """Raised when execution cannot be safely delegated."""


class ExecutionBackend(ABC):
    @property
    @abstractmethod
    def info(self) -> ExecutionBackendInfo:
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        raise NotImplementedError


class ExecutionGateway:
    """Central execution boundary with fail-closed authorization and policy binding."""

    def __init__(self, *, backends: Iterable[ExecutionBackend] = (), settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        backend_items = tuple(backends)
        self._backends = {backend.info.backend_id: backend for backend in backend_items}
        if len(self._backends) != len(backend_items):
            raise ExecutionGatewayError("backend IDs must be unique")
        for backend in backend_items:
            backend.info.validate()

    def list_backends(self, *, available_only: bool = False) -> tuple[ExecutionBackendInfo, ...]:
        values = (backend.info for backend in self._backends.values())
        if available_only:
            values = (info for info in values if info.available)
        return tuple(sorted(values, key=lambda item: item.backend_id))

    def execute(self, request: ExecutionRequest, *, authorization: ExecutionAuthorization | None = None,
                backend_id: str | None = None) -> ExecutionResult:
        request.validate(max_timeout_seconds=3600)
        auth = authorization or ExecutionAuthorization(False, "execution requires explicit authorization")
        try:
            auth.validate()
        except ValueError as exc:
            raise ExecutionGatewayError(str(exc)) from exc

        selected_id = auth.backend_id or backend_id or self._settings.execution_backend
        if auth.authorized:
            if auth.run_id != request.run_id or auth.worker_id != request.worker_id:
                raise ExecutionGatewayError("authorization scope does not match execution request")
            if auth.backend_id != selected_id:
                raise ExecutionGatewayError("authorization does not permit the selected backend")
            if request.needs_network and not auth.network_allowed:
                return self._denied(request, "network access is not authorized", selected_id)
        else:
            return self._denied(request, auth.reason, selected_id)

        backend = self._backends.get(selected_id)
        if backend is None:
            return ExecutionResult(execution_id=request.execution_id, run_id=request.run_id,
                status=ExecutionStatus.UNAVAILABLE, exit_code=None, stdout="",
                stderr=f"execution backend is not registered: {selected_id}", duration_ms=0, backend=selected_id)
        if not backend.info.available:
            return ExecutionResult(execution_id=request.execution_id, run_id=request.run_id,
                status=ExecutionStatus.UNAVAILABLE, exit_code=None, stdout="",
                stderr=f"execution backend is unavailable: {selected_id}", duration_ms=0, backend=selected_id)

        started = monotonic()
        try:
            result = backend.execute(request)
        except TimeoutError as exc:
            return ExecutionResult(execution_id=request.execution_id, run_id=request.run_id,
                status=ExecutionStatus.TIMEOUT, exit_code=None, stdout="", stderr=str(exc) or "execution timed out",
                duration_ms=_elapsed_ms(started), backend=selected_id)
        except Exception as exc:
            return ExecutionResult(execution_id=request.execution_id, run_id=request.run_id,
                status=ExecutionStatus.ERROR, exit_code=None, stdout="", stderr=f"{type(exc).__name__}: {exc}",
                duration_ms=_elapsed_ms(started), backend=selected_id)

        if result.execution_id != request.execution_id:
            raise ExecutionGatewayError("backend returned an inconsistent execution_id")
        if result.run_id not in (None, request.run_id):
            raise ExecutionGatewayError("backend returned an inconsistent run_id")
        if result.backend != selected_id:
            raise ExecutionGatewayError("backend returned inconsistent backend provenance")
        if result.run_id is None:
            result = ExecutionResult(execution_id=result.execution_id, run_id=request.run_id,
                status=result.status, exit_code=result.exit_code, stdout=result.stdout,
                stderr=result.stderr, duration_ms=result.duration_ms, artifacts=result.artifacts, backend=selected_id)
        result.validate()
        return result

    @staticmethod
    def _denied(request: ExecutionRequest, reason: str, backend_id: str) -> ExecutionResult:
        return ExecutionResult(execution_id=request.execution_id, run_id=request.run_id,
            status=ExecutionStatus.DENIED, exit_code=None, stdout="", stderr=reason,
            duration_ms=0, backend=backend_id)


def _elapsed_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))
