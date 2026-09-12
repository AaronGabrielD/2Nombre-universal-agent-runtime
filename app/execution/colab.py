"""HTTP adapter for a user-hosted Google Colab execution service."""
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
    """Raised when the remote Colab execution API cannot be trusted."""


class ColabExecutionBackend(ExecutionBackend):
    MAX_RESPONSE_BYTES = 4 * 1024 * 1024
    MAX_ERROR_BYTES = 4096

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
        request.validate(max_timeout_seconds=3600)
        if not request.idempotency_key:
            raise ColabBackendError("Colab execution requires an explicit idempotency_key")
        payload = {
            "execution_id": request.execution_id,
            "run_id": request.run_id,
            "worker_id": request.worker_id,
            "language": request.language,
            "code": request.code,
            "timeout_seconds": request.timeout_seconds,
            "needs_network": request.needs_network,
            "environment": dict(request.environment),
            "idempotency_key": request.idempotency_key,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Execution-Id": request.execution_id,
            "X-Idempotency-Key": request.idempotency_key,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        started = monotonic()
        try:
            with urlopen(
                Request(
                    f"{self._base_url}{self._execute_path}",
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                    method="POST",
                ),
                timeout=min(self._timeout_seconds, request.timeout_seconds),
            ) as response:
                raw = _read_bounded(response, self.MAX_RESPONSE_BYTES)
        except HTTPError as exc:
            raise ColabBackendError(
                f"Colab service returned HTTP {exc.code}: "
                f"{_read_error_body(exc, self.MAX_ERROR_BYTES) or exc.reason}"
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
        return _result_from_payload(decoded, request, _elapsed_ms(started))


def _normalize_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url cannot be empty")
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    return base_url.strip().rstrip("/")


def _read_bounded(stream, limit: int) -> bytes:
    if limit < 1:
        raise ValueError("limit must be positive")
    try:
        data = stream.read(limit + 1)
    except TypeError:
        data = stream.read()
    if len(data) > limit:
        raise ColabBackendError("Colab response exceeds configured size limit")
    return data


def _read_error_body(exc: HTTPError, limit: int) -> str:
    try:
        return exc.read(limit).decode("utf-8", errors="replace").strip()[:limit]
    except OSError:
        return ""


def _result_from_payload(
    payload: object,
    request: ExecutionRequest,
    elapsed_ms: int,
) -> ExecutionResult:
    if not isinstance(payload, dict):
        raise ColabBackendError("Colab response must be a JSON object")
    if payload.get("execution_id") != request.execution_id:
        raise ColabBackendError("Colab response execution_id does not match the request")
    if payload.get("run_id", request.run_id) != request.run_id:
        raise ColabBackendError("Colab response run_id does not match the request")
    try:
        status = ExecutionStatus(payload.get("status", ExecutionStatus.ERROR.value))
    except (ValueError, TypeError) as exc:
        raise ColabBackendError("invalid execution status from Colab") from exc
    stdout, stderr = payload.get("stdout", ""), payload.get("stderr", "")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise ColabBackendError("Colab response stdout/stderr must be strings")
    exit_code = payload.get("exit_code")
    if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
        raise ColabBackendError("Colab response exit_code must be an integer or null")
    duration = payload.get("duration_ms", elapsed_ms)
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
        raise ColabBackendError("Colab response duration_ms must be a non-negative integer")
    artifacts = _parse_artifacts(payload.get("artifacts", []))
    return ExecutionResult(
        execution_id=request.execution_id,
        run_id=request.run_id,
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration,
        artifacts=artifacts,
        backend="colab",
    )


def _parse_artifacts(raw: object) -> tuple[ArtifactRef, ...]:
    if not isinstance(raw, list) or len(raw) > 100:
        raise ColabBackendError("Colab response artifacts must be a list with at most 100 items")
    parsed: list[ArtifactRef] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ColabBackendError("each Colab artifact must be a JSON object")
        aid, name = item.get("artifact_id"), item.get("name")
        mime, uri = item.get("mime_type"), item.get("uri")
        if not isinstance(aid, str) or not aid.strip() or not isinstance(name, str) or not name.strip():
            raise ColabBackendError("artifact_id and name must be non-empty strings")
        if mime is not None and not isinstance(mime, str):
            raise ColabBackendError("artifact mime_type must be a string or null")
        if uri is not None and not isinstance(uri, str):
            raise ColabBackendError("artifact uri must be a string or null")
        parsed.append(ArtifactRef(artifact_id=aid, name=name, mime_type=mime, uri=uri))
    return tuple(parsed)


def _elapsed_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))
