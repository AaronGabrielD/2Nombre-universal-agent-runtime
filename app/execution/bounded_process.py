"""Bounded subprocess execution for untrusted worker code."""
from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Mapping, Sequence


class BoundedProcessError(RuntimeError):
    """Raised when bounded subprocess output cannot be collected safely."""


@dataclass(frozen=True, slots=True)
class BoundedProcessResult:
    """Process completion plus output capped in parent memory."""

    returncode: int
    timed_out: bool
    stdout: bytes
    stderr: bytes


def run_bounded_process(
    command: Sequence[str],
    *,
    cwd: str | Path,
    env: Mapping[str, str],
    timeout: int | float,
    max_output_bytes: int,
) -> BoundedProcessResult:
    """Run a child while draining both output streams and retaining bounded data."""
    if not command:
        raise ValueError("command cannot be empty")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if max_output_bytes < 1:
        raise ValueError("max_output_bytes must be positive")

    kwargs = {
        "cwd": str(cwd),
        "env": dict(env),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(list(command), **kwargs)
    stdout_holder: list[bytes] = [b""]
    stderr_holder: list[bytes] = [b""]
    output_errors: list[BaseException] = []

    stdout_thread = threading.Thread(
        target=_drain_pipe,
        args=(process.stdout, max_output_bytes, stdout_holder, output_errors),
        daemon=True,
        name="uar-bounded-stdout-reader",
    )
    stderr_thread = threading.Thread(
        target=_drain_pipe,
        args=(process.stderr, max_output_bytes, stderr_holder, output_errors),
        daemon=True,
        name="uar-bounded-stderr-reader",
    )
    stdout_thread.start()
    stderr_thread.start()

    timed_out = False
    try:
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_tree(process)
            returncode = process.wait()
    finally:
        stdout_thread.join()
        stderr_thread.join()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    if output_errors:
        error = output_errors[0]
        raise BoundedProcessError(
            f"failed to collect bounded subprocess output: {type(error).__name__}: {error}"
        ) from error

    return BoundedProcessResult(
        returncode=returncode,
        timed_out=timed_out,
        stdout=stdout_holder[0],
        stderr=stderr_holder[0],
    )


def _drain_pipe(
    stream,
    limit: int,
    holder: list[bytes],
    errors: list[BaseException],
) -> None:
    try:
        if stream is None:
            holder[0] = b""
            return
        capture_limit = limit + 1
        captured = bytearray()
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            if len(captured) < capture_limit:
                captured.extend(chunk[: capture_limit - len(captured)])
        holder[0] = bytes(captured)
    except BaseException as exc:
        errors.append(exc)


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Stop the process and descendants so timeout cleanup cannot leave writers alive."""
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except (OSError, ProcessLookupError):
            pass
    elif os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
            )
            return
        except OSError:
            pass
    process.kill()
