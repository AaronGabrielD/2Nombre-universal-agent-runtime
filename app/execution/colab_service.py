"""HTTP execution service intended to run inside a Google Colab runtime."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any
from urllib.parse import quote, unquote, urlparse

from app.execution.policy import ExecutionPolicyError, PythonExecutionPolicy


class ColabExecutionServiceError(ValueError):
    """Raised for invalid execution-service configuration or requests."""


class ExecutionInProgressError(ColabExecutionServiceError):
    """Raised when a duplicate request is already executing."""


class ExecutionConflictError(ColabExecutionServiceError):
    """Raised when an execution identity is reused for different work."""


class ExecutionServiceConfig:
    """Configuration read from environment variables at process startup."""

    def __init__(self) -> None:
        self.bind_host = os.getenv("RUNTIME_BIND_HOST", "0.0.0.0")
        self.port = _int_env("RUNTIME_PORT", 8000, minimum=1, maximum=65535)
        self.token = os.getenv("RUNTIME_EXECUTION_TOKEN", "").strip()
        self.artifact_root = Path(
            os.getenv("RUNTIME_ARTIFACT_ROOT", "/content/universal-agent-runtime-artifacts")
        ).resolve()
        self.execution_db_path = Path(
            os.getenv("RUNTIME_EXECUTION_DB", str(self.artifact_root / "executions.db"))
        ).expanduser().resolve()
        self.max_request_bytes = _int_env("RUNTIME_MAX_REQUEST_BYTES", 2 * 1024 * 1024, minimum=1024)
        self.max_output_bytes = _int_env("RUNTIME_MAX_OUTPUT_BYTES", 256 * 1024, minimum=1024)
        self.max_artifact_bytes = _int_env("RUNTIME_MAX_ARTIFACT_BYTES", 10 * 1024 * 1024, minimum=1024)
        self.max_total_artifact_bytes = _int_env(
            "RUNTIME_MAX_TOTAL_ARTIFACT_BYTES", 32 * 1024 * 1024, minimum=1024
        )
        self.max_artifacts = _int_env("RUNTIME_MAX_ARTIFACTS", 20, minimum=1, maximum=100)
        self.default_timeout_seconds = _int_env("RUNTIME_DEFAULT_TIMEOUT_SECONDS", 60, minimum=1, maximum=3600)
        self.max_timeout_seconds = _int_env("RUNTIME_MAX_TIMEOUT_SECONDS", 600, minimum=1, maximum=3600)
        self.allow_network_requests = _bool_env("RUNTIME_ALLOW_NETWORK", False)
        self.python_policy_mode = os.getenv("RUNTIME_PYTHON_POLICY", "restricted").strip().lower()
        self.public_base_url = os.getenv("RUNTIME_PUBLIC_BASE_URL", "").strip().rstrip("/")
        if self.python_policy_mode not in {"restricted", "unsafe"}:
            raise ColabExecutionServiceError("RUNTIME_PYTHON_POLICY must be 'restricted' or 'unsafe'")
        if not self.token:
            raise ColabExecutionServiceError("RUNTIME_EXECUTION_TOKEN must be configured")
        self.execution_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)


class ExecutionStore:
    """SQLite-backed idempotency and result authority for remote executions."""

    def __init__(self, database_path: Path) -> None:
        self.path = database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def reserve(
        self,
        *,
        execution_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as connection:
            try:
                connection.execute(
                    "INSERT INTO executions(execution_id,idempotency_key,request_fingerprint,status) VALUES(?,?,?,?)",
                    (execution_id, idempotency_key, request_fingerprint, "running"),
                )
                return None
            except sqlite3.IntegrityError:
                rows = connection.execute(
                    "SELECT execution_id,idempotency_key,request_fingerprint,status,result_json FROM executions WHERE execution_id = ? OR idempotency_key = ?",
                    (execution_id, idempotency_key),
                ).fetchall()
                for row in rows:
                    existing_execution_id, existing_key, existing_fingerprint, status, result_json = row
                    if (
                        existing_execution_id != execution_id
                        or existing_key != idempotency_key
                        or existing_fingerprint != request_fingerprint
                    ):
                        raise ExecutionConflictError("execution identity was reused for different work")
                    if status == "running":
                        raise ExecutionInProgressError("execution is already in progress")
                    if status == "completed" and result_json:
                        payload = json.loads(result_json)
                        if isinstance(payload, dict):
                            return payload
                raise ColabExecutionServiceError("stored execution record is invalid")

    def complete(self, *, execution_id: str, result: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as connection:
            updated = connection.execute(
                "UPDATE executions SET status = ?, result_json = ? WHERE execution_id = ? AND status = 'running'",
                ("completed", json.dumps(result, ensure_ascii=False, sort_keys=True), execution_id),
            ).rowcount
            if updated != 1:
                raise ColabExecutionServiceError("execution completion record was not writable")

    def get(self, *, execution_id: str, idempotency_key: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT idempotency_key,status,result_json FROM executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        if row is None:
            return None
        stored_key, status, result_json = row
        if stored_key != idempotency_key:
            raise ExecutionConflictError("execution idempotency key does not match stored authority")
        if status != "completed" or not result_json:
            return None
        payload = json.loads(result_json)
        return payload if isinstance(payload, dict) else None


class ColabExecutionRequestHandler(BaseHTTPRequestHandler):
    """Small JSON API for one remote execution backend."""

    server_version = "UniversalAgentRuntime-Colab/1.1"

    @property
    def config(self) -> ExecutionServiceConfig:
        return self.server.runtime_config  # type: ignore[attr-defined]

    @property
    def store(self) -> ExecutionStore:
        return self.server.execution_store  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok", "backend": "colab-service"})
            return
        if path.startswith("/executions/"):
            self._serve_execution(path)
            return
        if path.startswith("/artifacts/"):
            self._serve_artifact(path)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/execute":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            payload = self._read_json()
            response = self.server.executor.execute(payload)  # type: ignore[attr-defined]
        except (ExecutionInProgressError, ExecutionConflictError) as exc:
            self._send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        except ColabExecutionServiceError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal execution-service error"})
            print(f"[colab-service] internal error: {type(exc).__name__}: {exc}")
            return
        self._send_json(HTTPStatus.OK, response)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[colab-service] {self.address_string()} - {fmt % args}")

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not supplied:
            return False
        return secrets.compare_digest(supplied.strip(), self.config.token)

    def _read_json(self) -> dict[str, Any]:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ColabExecutionServiceError("Content-Length is required")
        try:
            size = int(content_length)
        except ValueError as exc:
            raise ColabExecutionServiceError("invalid Content-Length") from exc
        if size < 0 or size > self.config.max_request_bytes:
            raise ColabExecutionServiceError("request body exceeds configured limit")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ColabExecutionServiceError("request body was truncated")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ColabExecutionServiceError("request body must be UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ColabExecutionServiceError("request JSON must be an object")
        return payload

    def _serve_execution(self, path: str) -> None:
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        execution_id = unquote(path.rsplit("/", 1)[-1])
        if not _safe_identifier(execution_id):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        idempotency_key = self.headers.get("X-Idempotency-Key", "").strip()
        if not idempotency_key:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "X-Idempotency-Key is required"})
            return
        try:
            result = self.store.get(execution_id=execution_id, idempotency_key=idempotency_key)
        except ExecutionConflictError:
            self._send_json(HTTPStatus.CONFLICT, {"error": "idempotency key mismatch"})
            return
        if result is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._send_json(HTTPStatus.OK, result)

    def _serve_artifact(self, path: str) -> None:
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) < 3 or parts[0] != "artifacts":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        execution_id = parts[1]
        relative = Path(*parts[2:])
        if not _safe_identifier(execution_id) or relative.is_absolute() or ".." in relative.parts:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        root = (self.config.artifact_root / execution_id).resolve()
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not target.is_file() or target.is_symlink():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        size = target.stat().st_size
        if size > self.config.max_artifact_bytes:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with target.open("rb") as stream:
            shutil.copyfileobj(stream, self.wfile, length=64 * 1024)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ColabCodeExecutor:
    """Translate validated execution requests into local subprocesses."""

    def __init__(self, config: ExecutionServiceConfig, store: ExecutionStore | None = None) -> None:
        self.config = config
        self.policy = PythonExecutionPolicy()
        self.store = store or ExecutionStore(config.execution_db_path)

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = self._validate_request(payload)
        execution_id = request["execution_id"]
        fingerprint = _request_fingerprint(request)
        existing = self.store.reserve(
            execution_id=execution_id,
            idempotency_key=request["idempotency_key"],
            request_fingerprint=fingerprint,
        )
        if existing is not None:
            return existing
        result = self._execute_reserved(request, monotonic())
        self.store.complete(execution_id=execution_id, result=result)
        return result

    def _execute_reserved(self, request: dict[str, Any], started: float) -> dict[str, Any]:
        execution_id = request["execution_id"]
        timeout = request["timeout_seconds"]
        if request["needs_network"] and not self.config.allow_network_requests:
            return self._result(execution_id=execution_id, run_id=request["run_id"], status="denied", stdout="", stderr="network execution is disabled by service policy", exit_code=None, duration_ms=_duration_ms(started))
        if request["language"] != "python":
            return self._result(execution_id=execution_id, run_id=request["run_id"], status="unavailable", stdout="", stderr=f"unsupported language: {request['language']}", exit_code=None, duration_ms=_duration_ms(started))
        if self.config.python_policy_mode == "restricted":
            try:
                self.policy.validate(request["code"])
            except ExecutionPolicyError as exc:
                return self._result(execution_id=execution_id, run_id=request["run_id"], status="denied", stdout="", stderr=f"python execution blocked by policy: {exc}", exit_code=None, duration_ms=_duration_ms(started))
        execution_root = (self.config.artifact_root / execution_id).resolve()
        execution_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=f"uar-{execution_id[:12]}-", dir="/tmp") as tmp:
            workdir = Path(tmp).resolve()
            script = workdir / "main.py"
            script.write_text(request["code"], encoding="utf-8")
            environment = _execution_environment(request["environment"], workdir)
            completed = self._run_bounded_subprocess(
                script=script,
                workdir=workdir,
                environment=environment,
                timeout=timeout,
            )
            if completed["timed_out"]:
                return self._result(
                    execution_id=execution_id,
                    run_id=request["run_id"],
                    status="timeout",
                    stdout=_bounded_text(completed["stdout"], self.config.max_output_bytes),
                    stderr=_bounded_text(completed["stderr"], self.config.max_output_bytes)
                    or f"execution exceeded {timeout} seconds",
                    exit_code=None,
                    duration_ms=_duration_ms(started),
                )
            artifacts = self._collect_artifacts(workdir, execution_root, execution_id)
        return self._result(
            execution_id=execution_id,
            run_id=request["run_id"],
            status="success" if completed["returncode"] == 0 else "error",
            stdout=_bounded_text(completed["stdout"], self.config.max_output_bytes),
            stderr=_bounded_text(completed["stderr"], self.config.max_output_bytes),
            exit_code=completed["returncode"],
            duration_ms=_duration_ms(started),
            artifacts=artifacts,
        )

    def _run_bounded_subprocess(
        self,
        *,
        script: Path,
        workdir: Path,
        environment: dict[str, str],
        timeout: int,
    ) -> dict[str, Any]:
        process = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(workdir),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        stdout_holder: list[bytes] = [b""]
        stderr_holder: list[bytes] = [b""]
        stdout_error: list[BaseException] = []
        stderr_error: list[BaseException] = []

        stdout_thread = threading.Thread(
            target=_drain_pipe_bounded,
            args=(process.stdout, self.config.max_output_bytes, stdout_holder, stdout_error),
            daemon=True,
            name="uar-colab-stdout-reader",
        )
        stderr_thread = threading.Thread(
            target=_drain_pipe_bounded,
            args=(process.stderr, self.config.max_output_bytes, stderr_holder, stderr_error),
            daemon=True,
            name="uar-colab-stderr-reader",
        )
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        try:
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                returncode = process.wait()
        finally:
            stdout_thread.join()
            stderr_thread.join()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

        if stdout_error or stderr_error:
            error = (stdout_error + stderr_error)[0]
            raise ColabExecutionServiceError(
                f"failed to collect bounded subprocess output: {type(error).__name__}: {error}"
            ) from error

        return {
            "returncode": returncode,
            "timed_out": timed_out,
            "stdout": stdout_holder[0],
            "stderr": stderr_holder[0],
        }

    def _validate_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = ("execution_id", "run_id", "worker_id", "language", "code")
        for key in required:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ColabExecutionServiceError(f"{key} must be a non-empty string")
        if not _safe_identifier(payload["execution_id"]) or not _safe_identifier(payload["run_id"]) or not _safe_identifier(payload["worker_id"]):
            raise ColabExecutionServiceError("execution identifiers are invalid")
        language = payload["language"].strip().lower()
        timeout = payload.get("timeout_seconds", self.config.default_timeout_seconds)
        if not isinstance(timeout, int) or isinstance(timeout, bool):
            raise ColabExecutionServiceError("timeout_seconds must be an integer")
        if not 1 <= timeout <= self.config.max_timeout_seconds:
            raise ColabExecutionServiceError("timeout_seconds is outside the configured range")
        needs_network = payload.get("needs_network", False)
        if not isinstance(needs_network, bool):
            raise ColabExecutionServiceError("needs_network must be boolean")
        environment = payload.get("environment", {})
        if not isinstance(environment, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in environment.items()):
            raise ColabExecutionServiceError("environment must be a string-to-string object")
        idempotency_key = payload.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 256:
            raise ColabExecutionServiceError("idempotency_key must be a non-empty string of at most 256 characters")
        return {
            "execution_id": payload["execution_id"].strip(),
            "run_id": payload["run_id"].strip(),
            "worker_id": payload["worker_id"].strip(),
            "language": language,
            "code": payload["code"],
            "timeout_seconds": timeout,
            "needs_network": needs_network,
            "environment": dict(environment),
            "idempotency_key": idempotency_key.strip(),
        }

    def _collect_artifacts(self, workdir: Path, execution_root: Path, execution_id: str) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        total_bytes = 0
        for path in sorted(workdir.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(workdir)
            if relative == Path("main.py") or len(collected) >= self.config.max_artifacts:
                continue
            size = path.stat().st_size
            if size > self.config.max_artifact_bytes or total_bytes + size > self.config.max_total_artifact_bytes:
                continue
            destination = (execution_root / relative).resolve()
            try:
                destination.relative_to(execution_root)
            except ValueError:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination, follow_symlinks=False)
            if destination.is_symlink():
                destination.unlink(missing_ok=True)
                continue
            total_bytes += size
            collected.append({
                "artifact_id": f"artifact-{uuid.uuid4().hex}",
                "name": relative.as_posix(),
                "mime_type": None,
                "uri": self._artifact_uri(execution_id, relative),
            })
        return collected

    def _artifact_uri(self, execution_id: str, relative: Path) -> str:
        encoded = "/".join(quote(part, safe="") for part in relative.parts)
        if self.config.public_base_url:
            return f"{self.config.public_base_url}/artifacts/{quote(execution_id, safe='')}/{encoded}"
        return f"artifact://{execution_id}/{encoded}"

    @staticmethod
    def _result(*, execution_id: str, run_id: str, status: str, stdout: str, stderr: str, exit_code: int | None, duration_ms: int, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "execution_id": execution_id,
            "run_id": run_id,
            "status": status,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "artifacts": artifacts or [],
            "backend": "colab",
        }


class RuntimeColabHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying runtime configuration and the shared execution store."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], config: ExecutionServiceConfig) -> None:
        super().__init__(address, ColabExecutionRequestHandler)
        self.runtime_config = config
        self.execution_store = ExecutionStore(config.execution_db_path)
        self.executor = ColabCodeExecutor(config, self.execution_store)


def serve_forever(config: ExecutionServiceConfig | None = None) -> None:
    runtime_config = config or ExecutionServiceConfig()
    server = RuntimeColabHTTPServer((runtime_config.bind_host, runtime_config.port), runtime_config)
    print(
        f"Universal Agent Runtime Colab service listening on "
        f"{runtime_config.bind_host}:{runtime_config.port}"
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _request_fingerprint(request: dict[str, Any]) -> str:
    material = {
        "run_id": request["run_id"],
        "worker_id": request["worker_id"],
        "language": request["language"],
        "code": request["code"],
        "timeout_seconds": request["timeout_seconds"],
        "needs_network": request["needs_network"],
        "environment": dict(sorted(request["environment"].items())),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _execution_environment(requested: dict[str, str], workdir: Path) -> dict[str, str]:
    allowed_base = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    allowed_base.update({"HOME": str(workdir), "TMPDIR": str(workdir), "PYTHONUNBUFFERED": "1"})
    for key, value in requested.items():
        if _safe_environment_key(key):
            allowed_base[key] = value
    return allowed_base


def _safe_environment_key(value: str) -> bool:
    upper = value.upper()
    if not value or not value.replace("_", "A").isalnum() or value[0].isdigit():
        return False
    return not any(marker in upper for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "PRIVATE"))


def _drain_pipe_bounded(
    stream,
    limit: int,
    holder: list[bytes],
    errors: list[BaseException],
) -> None:
    try:
        if stream is None:
            holder[0] = b""
            return
        captured = bytearray()
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            if len(captured) < limit:
                captured.extend(chunk[: limit - len(captured)])
        holder[0] = bytes(captured)
    except BaseException as exc:
        errors.append(exc)


def _bounded_text(value: str | bytes, limit: int) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    if len(text.encode("utf-8")) <= limit:
        return text
    suffix = "\n[output truncated by execution service]"
    raw = text.encode("utf-8")[: max(0, limit - len(suffix.encode("utf-8")))]
    return raw.decode("utf-8", errors="ignore") + suffix


def _duration_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))


def _safe_identifier(value: str) -> bool:
    return bool(value) and len(value) <= 128 and all(char.isalnum() or char in "-_." for char in value)


def _int_env(name: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ColabExecutionServiceError(f"{name} must be an integer") from exc
    if value < minimum or (maximum is not None and value > maximum):
        raise ColabExecutionServiceError(f"{name} is outside the configured range")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ColabExecutionServiceError(f"{name} must be a boolean")


if __name__ == "__main__":
    serve_forever()
