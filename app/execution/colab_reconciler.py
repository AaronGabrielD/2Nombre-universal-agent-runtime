"""Explicit HTTP reconciler for an authoritative Colab execution service."""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from app.core.contracts import ArtifactRef, ExecutionResult, ExecutionStatus

from .reconciliation import ExecutionReconciler


class ColabReconcilerError(RuntimeError):
    """Raised when the remote Colab authority cannot provide valid evidence."""


class ColabExecutionReconciler(ExecutionReconciler):
    """Query persisted execution evidence from a protected Colab authority endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: int = 15,
        execution_path_prefix: str = "/executions",
    ) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._token = token.strip()
        if not self._token:
            raise ValueError("token cannot be empty")
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be >= 1")
        if not execution_path_prefix.startswith("/"):
            raise ValueError("execution_path_prefix must start with '/'")
        self._timeout_seconds = timeout_seconds
        self._execution_path_prefix = execution_path_prefix.rstrip("/")

    def reconcile(self, *, execution_id: str, idempotency_key: str) -> ExecutionResult | None:
        if not _safe_identifier(execution_id):
            raise ColabReconcilerError("invalid execution_id")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ColabReconcilerError("idempotency_key cannot be empty")

        url = f"{self._base_url}{self._execution_path_prefix}/{quote(execution_id, safe='')}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
                "X-Execution-Id": execution_id,
                "X-Idempotency-Key": idempotency_key,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code == 404:
                return None
            detail = _read_error_body(exc)
            raise ColabReconcilerError(
                f"Colab authority returned HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise ColabReconcilerError("Colab authority request timed out") from exc
        except URLError as exc:
            raise ColabReconcilerError(f"Colab authority connection failed: {exc.reason}") from exc
        except OSError as exc:
            raise ColabReconcilerError(f"Colab authority I/O failed: {exc}") from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ColabReconcilerError("Colab authority returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ColabReconcilerError("Colab authority response must be a JSON object")
        result = _result_from_payload(payload, execution_id)
        return result


def _result_from_payload(payload: dict[str, object], execution_id: str) -> ExecutionResult:
    if payload.get("execution_id") != execution_id:
        raise ColabReconcilerError("Colab authority returned an inconsistent execution_id")
    try:
        status = ExecutionStatus(payload.get("status"))
    except (TypeError, ValueError) as exc:
        raise ColabReconcilerError("Colab authority returned an invalid execution status") from exc

    stdout = payload.get("stdout", "")
    stderr = payload.get("stderr", "")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise ColabReconcilerError("stdout/stderr must be strings")

    exit_code = payload.get("exit_code")
    if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
        raise ColabReconcilerError("exit_code must be an integer or null")

    duration_ms = payload.get("duration_ms", 0)
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < 0:
        raise ColabReconcilerError("duration_ms must be a non-negative integer")

    artifacts_raw = payload.get("artifacts", [])
    if not isinstance(artifacts_raw, list):
        raise ColabReconcilerError("artifacts must be a list")
    artifacts: list[ArtifactRef] = []
    for item in artifacts_raw:
        if not isinstance(item, dict):
            raise ColabReconcilerError("each artifact must be a JSON object")
        artifact_id = item.get("artifact_id")
        name = item.get("name")
        mime_type = item.get("mime_type")
        uri = item.get("uri")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ColabReconcilerError("artifact_id must be a non-empty string")
        if not isinstance(name, str) or not name.strip():
            raise ColabReconcilerError("artifact name must be a non-empty string")
        if mime_type is not None and not isinstance(mime_type, str):
            raise ColabReconcilerError("artifact mime_type must be a string or null")
        if uri is not None and not isinstance(uri, str):
            raise ColabReconcilerError("artifact uri must be a string or null")
        artifacts.append(ArtifactRef(artifact_id=artifact_id, name=name, mime_type=mime_type, uri=uri))

    backend = payload.get("backend", "colab-authority")
    if not isinstance(backend, str) or not backend.strip():
        raise ColabReconcilerError("backend must be a non-empty string")

    return ExecutionResult(
        execution_id=execution_id,
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        artifacts=tuple(artifacts),
        backend=backend,
    )


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


def _safe_identifier(value: str) -> bool:
    return bool(value) and len(value) <= 128 and all(char.isalnum() or char in "-_." for char in value)
