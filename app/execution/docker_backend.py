"""Optional Docker execution backend with defense-in-depth isolation."""
from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Sequence

from app.core.contracts import ArtifactRef, ExecutionRequest, ExecutionResult, ExecutionStatus

from .bounded_process import BoundedProcessError, run_bounded_process
from .models import ExecutionBackendInfo
from .service import ExecutionBackend


class DockerExecutionBackend(ExecutionBackend):
    """Run Python workers in Docker with bounded output and artifact collection."""

    _SECRET_MARKERS = (
        "KEY",
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "CREDENTIAL",
        "PRIVATE",
    )

    def __init__(
        self,
        *,
        image: str = "python:3.12-alpine",
        docker_binary: str = "docker",
        allow_network: bool = False,
        memory: str = "512m",
        cpus: str = "1.0",
        pids_limit: int = 128,
        max_output_bytes: int = 256 * 1024,
        artifact_root: str | None = None,
        max_artifacts: int = 20,
        max_artifact_bytes: int = 10 * 1024 * 1024,
        max_total_artifact_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        if not isinstance(image, str) or not image.strip() or any(
            char in image for char in "\r\n"
        ):
            raise ValueError("image must be a non-empty single-line value")
        if not isinstance(docker_binary, str) or not docker_binary.strip():
            raise ValueError("docker_binary must be a non-empty string")
        if not isinstance(allow_network, bool):
            raise ValueError("allow_network must be boolean")
        if pids_limit < 16:
            raise ValueError("pids_limit must be at least 16")
        if max_output_bytes < 1024:
            raise ValueError("max_output_bytes must be at least 1024")
        if max_artifacts < 1:
            raise ValueError("max_artifacts must be at least 1")
        if max_artifact_bytes < 1 or max_total_artifact_bytes < max_artifact_bytes:
            raise ValueError("Docker artifact byte limits are invalid")
        self.image = image.strip()
        self.docker_binary = docker_binary.strip()
        self.allow_network = allow_network
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.max_output_bytes = max_output_bytes
        self.max_artifacts = max_artifacts
        self.max_artifact_bytes = max_artifact_bytes
        self.max_total_artifact_bytes = max_total_artifact_bytes
        self.artifact_root = (
            Path(artifact_root).expanduser().resolve() if artifact_root else None
        )
        if self.artifact_root:
            self.artifact_root.mkdir(parents=True, exist_ok=True)

    @property
    def info(self) -> ExecutionBackendInfo:
        return ExecutionBackendInfo(
            "docker",
            "Hardened Docker execution backend",
            shutil.which(self.docker_binary) is not None,
        )

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        request.validate(max_timeout_seconds=3600)
        started = monotonic()
        if request.language.strip().lower() != "python":
            return self._result(
                request, ExecutionStatus.UNAVAILABLE, "", "unsupported language", None, started
            )
        if not self.info.available:
            return self._result(
                request,
                ExecutionStatus.UNAVAILABLE,
                "",
                "docker executable is unavailable",
                None,
                started,
            )
        if request.needs_network and not self.allow_network:
            return self._result(
                request,
                ExecutionStatus.DENIED,
                "",
                "network execution is disabled by Docker backend policy",
                None,
                started,
            )

        with TemporaryDirectory(prefix=f"uar-docker-{request.execution_id[:12]}-") as temp:
            root = Path(temp).resolve()
            script = root / "main.py"
            script.write_text(request.code, encoding="utf-8")
            command = self._docker_command(request, root)
            try:
                completed = run_bounded_process(
                    command,
                    cwd=root,
                    env={"PATH": shutil.which(self.docker_binary) or "", "HOME": "/tmp"},
                    timeout=request.timeout_seconds,
                    max_output_bytes=self.max_output_bytes,
                )
            except BoundedProcessError as exc:
                return self._result(
                    request,
                    ExecutionStatus.ERROR,
                    "",
                    str(exc),
                    None,
                    started,
                )
            except OSError as exc:
                return self._result(
                    request,
                    ExecutionStatus.ERROR,
                    "",
                    f"docker launch failed: {exc}",
                    None,
                    started,
                )

            stdout = self._bounded(completed.stdout)
            stderr = self._bounded(completed.stderr)
            if completed.timed_out:
                return self._result(
                    request,
                    ExecutionStatus.TIMEOUT,
                    stdout,
                    stderr or "container execution timed out",
                    None,
                    started,
                )
            status = (
                ExecutionStatus.SUCCESS
                if completed.returncode == 0
                else ExecutionStatus.ERROR
            )
            artifacts = self._persist_artifacts(root, request.execution_id)
            return self._result(
                request,
                status,
                stdout,
                stderr,
                completed.returncode,
                started,
                artifacts,
            )

    def _docker_command(self, request: ExecutionRequest, root: Path) -> list[str]:
        network = "bridge" if request.needs_network else "none"
        command = [
            self.docker_binary,
            "run",
            "--rm",
            "--pull=never",
            "--network",
            network,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            self.memory,
            "--cpus",
            self.cpus,
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m",
            "--user",
            "65532:65532",
            "--mount",
            f"type=bind,src={root},dst=/workspace,rw",
            "--workdir",
            "/workspace",
            "--env",
            "PYTHONUNBUFFERED=1",
        ]
        for key, value in request.environment.items():
            if self._safe_environment_key(key):
                command.extend(["--env", f"{key}={value}"])
        command.extend([self.image, "python", "-I", "/workspace/main.py"])
        return command

    def _persist_artifacts(
        self, root: Path, execution_id: str
    ) -> tuple[ArtifactRef, ...]:
        if self.artifact_root is None:
            return ()
        destination_root = (self.artifact_root / execution_id).resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        artifacts: list[ArtifactRef] = []
        total = 0
        for path in sorted(root.rglob("*")):
            if path.name == "main.py" or path.is_symlink() or not path.is_file():
                continue
            if len(artifacts) >= self.max_artifacts:
                break
            try:
                relative = path.relative_to(root)
                size = path.stat().st_size
            except (OSError, ValueError):
                continue
            if size > self.max_artifact_bytes:
                continue
            if total + size > self.max_total_artifact_bytes:
                break
            destination = (destination_root / relative).resolve()
            try:
                destination.relative_to(destination_root)
            except ValueError:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(path, destination, follow_symlinks=False)
            except OSError:
                continue
            if destination.is_symlink():
                destination.unlink(missing_ok=True)
                continue
            total += size
            artifacts.append(
                ArtifactRef(
                    artifact_id=f"artifact-{execution_id}-{len(artifacts)}",
                    name=relative.as_posix(),
                    uri=f"artifact://{execution_id}/{relative.as_posix()}",
                )
            )
        return tuple(artifacts)

    def _bounded(self, value: bytes) -> str:
        encoded = bytes(value)
        if len(encoded) <= self.max_output_bytes:
            return encoded.decode("utf-8", errors="replace")
        return (
            encoded[: self.max_output_bytes].decode("utf-8", errors="ignore")
            + "\n[output truncated]"
        )

    @classmethod
    def _safe_environment_key(cls, key: str) -> bool:
        if not isinstance(key, str) or not key or len(key) > 128:
            return False
        if not (key[0].isalpha() or key[0] == "_"):
            return False
        if not all(char.isalnum() or char == "_" for char in key):
            return False
        return not any(marker in key.upper() for marker in cls._SECRET_MARKERS)

    @staticmethod
    def _result(
        request: ExecutionRequest,
        status: ExecutionStatus,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        started: float,
        artifacts: Sequence[ArtifactRef] = (),
    ) -> ExecutionResult:
        return ExecutionResult(
            execution_id=request.execution_id,
            run_id=request.run_id,
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=max(0, int((monotonic() - started) * 1000)),
            artifacts=tuple(artifacts),
            backend="docker",
        )
