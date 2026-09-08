"""HTTP adapter for a user-hosted Google Colab execution service.

The adapter speaks a small JSON-over-HTTP contract and implements M08's
ExecutionBackend interface. It does not execute code itself; the remote Colab
service is responsible for that work.
"""
from __future__ import annotations

import json
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.core.contracts import ArtifactRef, ExecutionRequest, ExecutionResult, ExecutionStatus

from .models import ExecutionBackendInfo
from .service import ExecutionBackend, ExecutionGatewayError


class ColabBackendError(ExecutionGatewayError):
    """Raised when the Colab service cannot be reached or returns invalid data."""


class ColabExecutionBackend(ExecutionBackend):
    """Delegate one validated execution request to a remote Colab service."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout_seconds: int = 60,
        execute_path: str = "/execute",
        available: bool = True,
    ) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._token = token.strip() if token else None
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be >= 1")
        if not execute_path.startswith("/"):
            raise ValueError("execute_path must start with '/'")
        self._timeout_seconds = timeout_seconds
        self._execute_path = execute_path
        self._available = available

    @property
    def info(self) -> ExecutionBackendInfo:
        return ExecutionBackendInfo(
            backend_id="colab",
            name="Google Colab HTTP execution backend",
            available=self._available,
        )

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        payload = {
            "execution_id": request.execution_id,
            "run_id": request.run_id,
            "worker_id": request.worker_id,
            "language": request.language,
            "code": request.code,
            "timeout_seconds": request.timeout_seconds,
            "needs_network": request.needs_network,
            "environment": dict(request.environment),
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        request_url = f"{self._base_url}{self._execute_path}"
        http_request = Request(request_url, data=body, headers=headers, method="POST")
        started = monotonic()
        try:
            with urlopen(http_request, timeout=min(self._timeout_seconds, request.timeout_seconds)) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = _read_error_body(exc)
            raise ColabBackendError(
                f"Colab service returned HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise TimeoutError("Colab execution request timed out") from exc
        except URLError as exc:
            raise ColabBackendError(f"Colab service connection failed: {exc.reason}") from exc
        except OSError as exc:
            raise ColabBackendError(f"Colab service I/O failed: {exc}") from exc

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ColabBackendError("Colab service returned invalid JSON") from exc

        result = _result_from_payload(decoded, request, _elapsed_ms(started))
        return result


def _normalize_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url cannot be empty")
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    return base_url.strip().rstrip("/")


def _read_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace").strip()[:1000]
    except OSError:
        return ""


def _result_from_payload(
    payload: object,
    request: ExecutionRequest,
    elapsed_ms: int,
) -> ExecutionResult:
    if not isinstance(payload, dict):
        raise ColabBackendError("Colab response must be a JSON object")

    execution_id = payload.get("execution_id")
    if execution_id != request.execution_id:
        raise ColabBackendError("Colab response execution_id does not match the request")

    raw_status = payload.get("status", ExecutionStatus.ERROR.value)
    try:
        status = ExecutionStatus(raw_status)
    except (ValueError, TypeError) as exc:
        raise ColabBackendError(f"invalid execution status from Colab: {raw_status!r}") from exc

    stdout = payload.get("stdout", "")
    stderr = payload.get("stderr", "")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise ColabBackendError("Colab response stdout/stderr must be strings")

    exit_code = payload.get("exit_code")
    if exit_code is not None and not isinstance(exit_code, int):
        raise ColabBackendError("Colab response exit_code must be an integer or null")

    remote_duration = payload.get("duration_ms", elapsed_ms)
    if not isinstance(remote_duration, int) or remote_duration < 0:
        raise ColabBackendError("Colab response duration_ms must be a non-negative integer")

    artifacts = _parse_artifacts(payload.get("artifacts", ()))
    backend = payload.get("backend", "colab")
    if not isinstance(backend, str) or not backend.strip():
        raise ColabBackendError("Colab response backend must be a non-empty string")

    return ExecutionResult(
        execution_id=request.execution_id,
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=remote_duration,
        artifacts=artifacts,
        backend=backend,
    )


def _parse_artifacts(raw_artifacts: object) -> tuple[ArtifactRef, ...]:
    if not isinstance(raw_artifacts, list):
        raise ColabBackendError("Colab response artifacts must be a list")

    parsed: list[ArtifactRef] = []
    for item in raw_artifacts:
        if not isinstance(item, dict):
            raise ColabBackendError("each Colab artifact must be a JSON object")
        artifact_id = item.get("artifact_id")
        name = item.get("name")
        mime_type = item.get("mime_type")
        uri = item.get("uri")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ColabBackendError("artifact_id must be a non-empty string")
        if not isinstance(name, str) or not name.strip():
            raise ColabBackendError("artifact name must be a non-empty string")
        if mime_type is not None and not isinstance(mime_type, str):
            raise ColabBackendError("artifact mime_type must be a string or null")
        if uri is not None and not isinstance(uri, str):
            raise ColabBackendError("artifact uri must be a string or null")
        parsed.append(
            ArtifactRef(
                artifact_id=artifact_id,
                name=name,
                mime_type=mime_type,
                uri=uri,
            )
        )
    return tuple(parsed)


def _elapsed_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))
