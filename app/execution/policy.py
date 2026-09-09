"""Static admission policy for Python execution in the Colab service."""
from __future__ import annotations

import ast
from dataclasses import dataclass


class ExecutionPolicyError(ValueError):
    """Raised when code violates the configured execution admission policy."""


@dataclass(frozen=True, slots=True)
class PythonExecutionPolicy:
    """Block common process/network escape primitives before subprocess execution.

    This is defense-in-depth, not a security sandbox. Python code can remain
    difficult to constrain perfectly with static inspection alone.
    """

    blocked_modules: frozenset[str] = frozenset({
        "os", "subprocess", "socket", "ssl", "urllib", "http", "requests",
        "httpx", "aiohttp", "ftplib", "paramiko", "websocket", "ctypes",
        "cffi", "multiprocessing", "signal", "resource", "sys", "importlib",
    })
    blocked_calls: frozenset[str] = frozenset({
        "eval", "exec", "compile", "breakpoint", "__import__",
    })
    blocked_attributes: frozenset[str] = frozenset({
        "system", "popen", "spawn", "fork", "forkserver", "run", "call",
        "check_call", "check_output", "Popen", "create_connection",
    })

    def validate(self, code: str) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ExecutionPolicyError("code cannot be empty")
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            raise ExecutionPolicyError(f"invalid Python syntax: {exc.msg}") from exc

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._check_module(alias.name)
            elif isinstance(node, ast.ImportFrom):
                self._check_module(node.module or "")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.blocked_calls:
                    raise ExecutionPolicyError(f"blocked call: {node.func.id}")
                if isinstance(node.func, ast.Attribute) and node.func.attr in self.blocked_attributes:
                    raise ExecutionPolicyError(f"blocked attribute call: {node.func.attr}")
            elif isinstance(node, ast.Attribute) and node.attr in self.blocked_attributes:
                raise ExecutionPolicyError(f"blocked attribute access: {node.attr}")

    def _check_module(self, module: str) -> None:
        root = module.split(".", 1)[0]
        if root in self.blocked_modules:
            raise ExecutionPolicyError(f"blocked module import: {module}")
