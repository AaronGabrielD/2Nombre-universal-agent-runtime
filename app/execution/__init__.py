"""Execution gateway and interchangeable backend adapters (M08)."""

from .colab import ColabBackendError, ColabExecutionBackend
from .docker_backend import DockerExecutionBackend
from .models import ExecutionAuthorization, ExecutionBackendInfo
from .service import ExecutionBackend, ExecutionGateway, ExecutionGatewayError

__all__ = [
    "ColabBackendError",
    "ColabExecutionBackend",
    "DockerExecutionBackend",
    "ExecutionAuthorization",
    "ExecutionBackendInfo",
    "ExecutionBackend",
    "ExecutionGateway",
    "ExecutionGatewayError",
]
