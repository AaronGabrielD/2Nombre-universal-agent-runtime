"""Explicit authoritative reconciliation client for the Colab execution service."""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.contracts import ArtifactRef, ExecutionResult, ExecutionStatus
from app.execution.reconciliation import ExecutionReconciler


class ColabReconcilerError(ValueError):
    """Raised when the Colab service cannot provide valid authoritative evidence."""


class ColabExecutionReconciler(ExecutionReconciler):
    """Query persisted Colab execution evidence by execution identifier."""

    def __init__(self, *, base_url: str, token: str | None = None, timeout_seconds: int = 30) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url cannot be empty")
        self._base_url = base_url.strip().rstrip("/")
        self._token = token.strip() if token else None
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be >= 1")
        self._timeout_seconds = timeout_seconds

    def reconcile(self, *, execution_id: str, idempotency_key: str) -> ExecutionResult | None:
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ColabReconcilerError("execution_id cannot be empty")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ColabReconcilerError("idempotency_key cannot be empty")
        request = Request(
            f"{self._base_url}/executions/{execution_id}",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise ColabReconcilerError(
                f"Colab reconciliation returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise ColabReconcilerError("Colab reconciliation request timed out") from exc
        except URLError as exc:
            raise ColabReconcilerError(f"Colab reconciliation connection failed: {exc.reason}") from exc
        except OSError as exc:
            raise ColabReconcilerError(f"Colab reconciliation I/O failed: {exc}") from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ColabReconcilerError("Colab reconciliation returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ColabReconcilerError("Colab reconciliation response must be a JSON object")
        if payload.get("execution_id") != execution_id:
            raise ColabReconcilerError("Colab reconciliation returned an inconsistent execution_id")
        return _result_from_payload(payload)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers


def _result_from_payload(payload: dict[str, object]) -> ExecutionResult:
    try:
        status = ExecutionStatus(payload.get("status"))
    except (ValueError, TypeError) as exc:
        raise ColabReconcilerError("invalid execution status in Colab evidence") from exc

    stdout = payload.get("stdout", "")
    stderr = payload.get("stderr", "")
    exit_code = payload.get("exit_code")
    duration_ms = payload.get("duration_ms")
    backend = payload.get("backend", "colab-service")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise ColabReconcilerError("Colab evidence stdout/stderr must be strings")
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
        raise ColabReconcilerError("Colab evidence exit_code must be an integer or null")
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0:
        raise ColabReconcilerError("Colab evidence duration_ms must be a non-negative integer")
    if not isinstance(backend, str) or not backend.strip():
        raise ColabReconcilerError("Colab evidence backend must be a non-empty string")

    raw_artifacts = payload.get("artifacts", [])
    if not isinstance(raw_artifacts, list):
        raise ColabReconcilerError("Colab evidence artifacts must be a list")
    artifacts: list[ArtifactRef] = []
    for item in raw_artifacts:
        if not isinstance(item, dict):
            raise ColabReconcilerError("Colab evidence artifact must be an object")
        artifact_id = item.get("artifact_id")
        name = item.get("name")
        mime_type = item.get("mime_type")
        uri = item.get("uri")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ColabReconcilerError("Colab evidence artifact_id is invalid")
        if not isinstance(name, str) or not name.strip():
            raise ColabReconcilerError("Colab evidence artifact name is invalid")
        if mime_type is not None and not isinstance(mime_type, str):
            raise ColabReconcilerError("Colab evidence mime_type is invalid")
        if uri is not None and not isinstance(uri, str):
            raise ColabReconcilerError("Colab evidence uri is invalid")
        artifacts.append(
            ArtifactRef(artifact_id=artifact_id, name=name, mime_type=mime_type, uri=uri)
        )

    execution_id = payload.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise ColabReconcilerError("Colab evidence execution_id is invalid")
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
