"""Provider-native Gemini worker adapter used when CrewAI is unavailable."""
from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings, get_settings
from app.core.contracts import TaskSpec
from app.llm.gemini import GeminiAdapter
from app.llm.interfaces import GenerationRequest, LLMProvider
from app.workers.models import WorkerInstance
from app.workers.runtime import WorkerExecutionTask

from .crewai_adapter import WorkerExecutionPlan


class GeminiWorkerAdapterError(RuntimeError):
    """Raised when Gemini cannot produce a valid worker execution plan."""


_SYSTEM_PROMPT = """You are a worker inside the Universal Agent Runtime.

Your job is ONLY to produce an execution plan for the supplied worker task.
Do not execute code, call external tools, or claim human approval.
Return only one JSON object with these keys:
summary, language, code, timeout_seconds, needs_network, environment.

The code must be self-contained executable code.
Default to Python unless another language is explicitly required.
Use needs_network=true only when network access is genuinely required by the task.
Never include secrets, credentials, API keys, or private tokens in environment.
Do not wrap the JSON in markdown fences.
"""


class GeminiWorkerAdapter:
    """Generate provider-neutral worker execution plans directly with Gemini.

    This is the dependency-free fallback for the optional CrewAI adapter. It keeps
    execution, authorization, and human approval under the runtime's own control.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        provider: LLMProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._provider = provider or GeminiAdapter(self.settings)

    def build_execution_plan(
        self,
        *,
        worker: WorkerInstance,
        task: TaskSpec,
        context: dict[str, Any] | None = None,
    ) -> WorkerExecutionPlan:
        if not worker.run_id.strip():
            raise GeminiWorkerAdapterError("worker.run_id cannot be empty")
        task.validate()
        if task.worker_id != worker.worker_id:
            raise GeminiWorkerAdapterError("task.worker_id must match worker.worker_id")

        payload = {
            "worker": {
                "worker_id": worker.worker_id,
                "role": worker.role,
                "mission": worker.mission,
            },
            "task": {
                "task_id": task.task_id,
                "description": task.description,
                "expected_output": task.expected_output,
                "required_tools": list(task.required_tools),
            },
            "context": context or {},
        }
        generation = self._provider.generate(
            GenerationRequest(
                model=self.settings.gemini_model_worker,
                contents=json.dumps(payload, ensure_ascii=False, default=str),
                system_instruction=_SYSTEM_PROMPT,
                temperature=min(self.settings.gemini_temperature, 0.2),
                metadata={"component": "gemini_worker_adapter"},
            )
        )
        data = self._decode_json(generation.text)
        language = data.get("language", "python")
        code = data.get("code")
        summary = data.get("summary", "")
        needs_network = data.get("needs_network", False)
        timeout_seconds = data.get("timeout_seconds", self.settings.default_execution_timeout_seconds)
        environment = data.get("environment", {})

        if not isinstance(language, str) or not language.strip():
            raise GeminiWorkerAdapterError("generated language must be a non-empty string")
        if not isinstance(code, str) or not code.strip():
            raise GeminiWorkerAdapterError("generated code must be a non-empty string")
        if not isinstance(summary, str):
            raise GeminiWorkerAdapterError("generated summary must be a string")
        if not isinstance(needs_network, bool):
            raise GeminiWorkerAdapterError("generated needs_network must be boolean")
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds < 1
        ):
            raise GeminiWorkerAdapterError("generated timeout_seconds must be a positive integer")
        if not isinstance(environment, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in environment.items()
        ):
            raise GeminiWorkerAdapterError("generated environment must be string-to-string")

        execution_task = WorkerExecutionTask(
            task=task,
            language=language.strip().lower(),
            code=code,
            timeout_seconds=timeout_seconds,
            needs_network=needs_network,
            environment=dict(environment),
        )
        execution_task.validate()
        return WorkerExecutionPlan(
            worker_id=worker.worker_id,
            task_id=task.task_id,
            summary=summary.strip(),
            execution_task=execution_task,
        )

    @staticmethod
    def _decode_json(text: str) -> dict[str, Any]:
        candidate = text.strip()
        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            candidate = "\n".join(lines).strip()
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise GeminiWorkerAdapterError(f"Gemini worker returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise GeminiWorkerAdapterError("Gemini worker response must be a JSON object")
        return payload
