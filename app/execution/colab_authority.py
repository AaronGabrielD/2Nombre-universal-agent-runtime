"""Concrete authoritative execution reconciliation for the Colab HTTP backend."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from app.core.contracts import ArtifactRef, ExecutionResult, ExecutionStatus

from .colab_service import ColabCodeExecutor, ColabExecutionRequestHandler, ExecutionServiceConfig
from .reconciliation import ExecutionReconciler


_SCHEMA_VERSION = 1
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class ColabAuthorityError(RuntimeError):
    """Raised when the authoritative Colab evidence endpoint is unavailable or invalid."""


class ColabExecutionEvidenceStore:
    """Durable JSON evidence store containing completed ExecutionResult payloads only."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def save(self, result: dict[str, object]) -> None:
        execution_id = result.get("execution_id")
        if not isinstance(execution_id, str) or not _SAFE_ID.fullmatch(execution_id):
            raise ColabAuthorityError("cannot persist evidence with an invalid execution_id")
        payload = {"schema_version": _SCHEMA_VERSION, "result": result}
        target = self.root / f"{execution_id}.json"
        with self._lock:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.root,
                prefix=f".{execution_id}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)

    def load(self, execution_id: str) -> dict[str, object] | None:
        if not _SAFE_ID.fullmatch(execution_id):
            return None
        target = self.root / f"{execution_id}.json"
        with self._lock:
            try:
                raw = target.read_text(encoding="utf-8")
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise ColabAuthorityError(f"unable to read execution evidence: {exc}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ColabAuthorityError("execution evidence is not valid JSON") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
            raise ColabAuthorityError("unsupported execution evidence schema")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ColabAuthorityError("execution evidence result must be an object")
        if result.get("execution_id") != execution_id:
            raise ColabAuthorityError("execution evidence execution_id does not match the requested ID")
        return result


class _RecordingColabExecutor:
    """Wrap the existing executor and durably record every terminal response."""

    def __init__(self, config: ExecutionServiceConfig, store: ColabExecutionEvidenceStore) -> None:
        self._executor = ColabCodeExecutor(config)
        self._store = store

    def execute(self, payload: dict[str, object]) -> dict[str, object]:
        result = self._executor.execute(payload)
        self._store.save(result)
        return result


class AuthoritativeColabRequestHandler(ColabExecutionRequestHandler):
    """Extend the existing authenticated service with an evidence lookup endpoint."""

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        prefix = "/executions/"
        if path.startswith(prefix):
            self._serve_execution(path[len(prefix):])
            return
        super().do_GET()

    def _serve_execution(self, raw_execution_id: str) -> None:
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        execution_id = unquote(raw_execution_id)
        if "/" in execution_id or not _SAFE_ID.fullmatch(execution_id):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        result = self.server.evidence_store.load(execution_id)  # type: ignore[attr-defined]
        if result is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "execution_not_found"})
            return
        self._send_json(HTTPStatus.OK, result)


class AuthoritativeColabHTTPServer(ThreadingHTTPServer):
    """Drop-in M12 server variant that records evidence for explicit reconciliation."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], config: ExecutionServiceConfig) -> None:
        super().__init__(address, AuthoritativeColabRequestHandler)
        self.runtime_config = config
        self.evidence_store = ColabExecutionEvidenceStore(
            Path(config.artifact_root) / "execution-evidence"
        )
        self.executor = _RecordingColabExecutor(config, self.evidence_store)


@dataclass(frozen=True, slots=True)
class ColabExecutionReconciler(ExecutionReconciler):
    """Query the authenticated Colab evidence endpoint without executing code."""

    base_url: str
    token: str | None = None
    timeout_seconds: int = 30
    executions_path: str = "/executions"

    def __post_init__(self) -> None:
        base_url = self.base_url.strip() if isinstance(self.base_url, str) else ""
        if not base_url or not urlparse(base_url).scheme or not urlparse(base_url).netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if urlparse(base_url).scheme not in {"http", "https"}:
            raise ValueError("base_url must use HTTP or HTTPS")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be >= 1")
        if not self.executions_path.startswith("/"):
            raise ValueError("executions_path must start with '/'")

    def reconcile(self, *, execution_id: str, idempotency_key: str) -> ExecutionResult | None:
        if not _SAFE_ID.fullmatch(execution_id):
            raise ValueError("execution_id is invalid")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty")

        url = f"{self.base_url.rstrip('/')}{self.executions_path.rstrip('/')}/{execution_id}"
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token.strip()}"
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code == HTTPStatus.NOT_FOUND:
                return None
            detail = _read_error_body(exc)
            raise ColabAuthorityError(
                f"Colab authority returned HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise ColabAuthorityError(f"Colab authority request failed: {exc}") from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ColabAuthorityError("Colab authority returned invalid JSON") from exc
        return _execution_result_from_payload(payload, execution_id)


def serve_authoritative_forever(config: ExecutionServiceConfig | None = None) -> None:
    """Run the authoritative Colab service variant."""
    runtime_config = config or ExecutionServiceConfig()
    server = AuthoritativeColabHTTPServer(
        (runtime_config.bind_host, runtime_config.port),
        runtime_config,
    )
    print(
        "Universal Agent Runtime authoritative Colab service listening on "
        f"{runtime_config.bind_host}:{runtime_config.port}"
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _execution_result_from_payload(payload: object, execution_id: str) -> ExecutionResult:
    if not isinstance(payload, dict):
        raise ColabAuthorityError("execution evidence must be a JSON object")
    if payload.get("execution_id") != execution_id:
        raise ColabAuthorityError("execution evidence execution_id does not match the requested ID")
    try:
        status = ExecutionStatus(payload.get("status"))
    except (ValueError, TypeError) as exc:
        raise ColabAuthorityError("execution evidence has an invalid status") from exc

    stdout = payload.get("stdout", "")
    stderr = payload.get("stderr", "")
    exit_code = payload.get("exit_code")
    duration_ms = payload.get("duration_ms", 0)
    backend = payload.get("backend", "colab-authority")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise ColabAuthorityError("execution evidence stdout/stderr must be strings")
    if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
        raise ColabAuthorityError("execution evidence exit_code must be an integer or null")
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < 0:
        raise ColabAuthorityError("execution evidence duration_ms must be a non-negative integer")
    if not isinstance(backend, str) or not backend.strip():
        raise ColabAuthorityError("execution evidence backend must be a non-empty string")

    raw_artifacts = payload.get("artifacts", [])
    if not isinstance(raw_artifacts, list):
        raise ColabAuthorityError("execution evidence artifacts must be a list")
    artifacts: list[ArtifactRef] = []
    for item in raw_artifacts:
        if not isinstance(item, dict):
            raise ColabAuthorityError("execution evidence artifact must be an object")
        artifact_id = item.get("artifact_id")
        name = item.get("name")
        mime_type = item.get("mime_type")
        uri = item.get("uri")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ColabAuthorityError("artifact_id must be a non-empty string")
        if not isinstance(name, str) or not name.strip():
            raise ColabAuthorityError("artifact name must be a non-empty string")
        if mime_type is not None and not isinstance(mime_type, str):
            raise ColabAuthorityError("artifact mime_type must be a string or null")
        if uri is not None and not isinstance(uri, str):
            raise ColabAuthorityError("artifact uri must be a string or null")
        artifacts.append(
            ArtifactRef(
                artifact_id=artifact_id,
                name=name,
                mime_type=mime_type,
                uri=uri,
            )
        )

    result = ExecutionResult(
        execution_id=execution_id,
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        artifacts=tuple(artifacts),
        backend=backend,
    )
    result.validate()
    return result


def _read_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace").strip()[:1000]
    except OSError:
        return ""
