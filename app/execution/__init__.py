"""Backend-neutral execution gateway (M08)."""

from .models import ExecutionAuthorization, ExecutionBackendInfo
from .service import ExecutionBackend, ExecutionGateway, ExecutionGatewayError

__all__ = [
    "ExecutionAuthorization",
    "ExecutionBackendInfo",
    "ExecutionBackend",
    "ExecutionGateway",
    "ExecutionGatewayError",
]
