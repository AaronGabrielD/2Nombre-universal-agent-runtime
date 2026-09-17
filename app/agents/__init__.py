"""Agent-orchestration adapters for the Universal Agent Runtime."""

from .crewai_adapter import CrewAIWorkerAdapter, CrewAIWorkerAdapterError, WorkerExecutionPlan
from .gemini_worker_adapter import GeminiWorkerAdapter, GeminiWorkerAdapterError

__all__ = [
    "CrewAIWorkerAdapter",
    "CrewAIWorkerAdapterError",
    "GeminiWorkerAdapter",
    "GeminiWorkerAdapterError",
    "WorkerExecutionPlan",
]
