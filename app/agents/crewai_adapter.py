"""Optional CrewAI adapter for generating executable worker plans.

CrewAI is an orchestration provider behind the runtime's own contracts. This
adapter never executes generated code and never resolves human-approval gates.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from app.core.config import Settings, get_settings
from app.core.contracts import TaskSpec
from app.workers.runtime import WorkerExecutionTask
from app.workers.models import WorkerInstance


class CrewAIWorkerAdapterError(RuntimeError):
    """Raised when CrewAI cannot produce a valid worker execution plan."""


@dataclass(frozen=True, slots=True)
class WorkerExecutionPlan:
    """Provider-neutral result returned by the CrewAI adapter."""

    worker_id: str
    task_id: str
    summary: str
    execution_task: WorkerExecutionTask


class CrewAIWorkerAdapter:
    """Turn a runtime worker/task contract into a CrewAI-generated execution plan.

    The adapter uses a single CrewAI agent per worker task. Worker dependency and
    parallelism remain controlled by M06; CrewAI is not allowed to become the
    runtime's workflow authority.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        crew_factory: Callable[[WorkerInstance, TaskSpec], Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._crew_factory = crew_factory or self._default_crew_factory

    def build_execution_plan(
        self,
        *,
        worker: WorkerInstance,
        task: TaskSpec,
        context: dict[str, Any] | None = None,
    ) -> WorkerExecutionPlan:
        if not worker.run_id.strip():
            raise CrewAIWorkerAdapterError("worker.run_id cannot be empty")
        task.validate()
        if task.worker_id != worker.worker_id:
            raise CrewAIWorkerAdapterError("task.worker_id must match worker.worker_id")

        crew = self._crew_factory(worker, task)
        try:
            result = crew.kickoff(inputs=context or {})
        except Exception as exc:
            raise CrewAIWorkerAdapterError(f"CrewAI worker planning failed: {exc}") from exc

        text = self._result_text(result)
        payload = self._decode_json(text)
        language = payload.get("language", "python")
        code = payload.get("code")
        summary = payload.get("summary", "")
        needs_network = payload.get("needs_network", False)
        timeout_seconds = payload.get("timeout_seconds", 60)
        environment = payload.get("environment", {})

        if not isinstance(language, str) or not language.strip():
            raise CrewAIWorkerAdapterError("generated language must be a non-empty string")
        if not isinstance(code, str) or not code.strip():
            raise CrewAIWorkerAdapterError("generated code must be a non-empty string")
        if not isinstance(summary, str):
            raise CrewAIWorkerAdapterError("generated summary must be a string")
        if not isinstance(needs_network, bool):
            raise CrewAIWorkerAdapterError("generated needs_network must be boolean")
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds < 1:
            raise CrewAIWorkerAdapterError("generated timeout_seconds must be a positive integer")
        if not isinstance(environment, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in environment.items()
        ):
            raise CrewAIWorkerAdapterError("generated environment must be string-to-string")

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

    def _default_crew_factory(self, worker: WorkerInstance, task: TaskSpec) -> Any:
        try:
            from crewai import Agent, Crew, LLM, Process, Task as CrewTask
        except ImportError as exc:
            raise CrewAIWorkerAdapterError(
                "crewai is not installed. Install the optional CrewAI dependency."
            ) from exc

        model = self.settings.gemini_model_worker
        api_key = self.settings.require_gemini_key()
        llm = LLM(
            model=f"gemini/{model}",
            api_key=api_key,
            temperature=self.settings.gemini_temperature,
        )
        agent = Agent(
            role=worker.role,
            goal=worker.mission,
            backstory=(
                "You are a worker inside a larger runtime. Follow the supplied task exactly. "
                "Do not execute code, call external tools, or claim human approval."
            ),
            llm=llm,
            allow_delegation=False,
            verbose=False,
            tools=[],
        )
        expected_output = (
            "Return ONLY JSON with keys: summary, language, code, timeout_seconds, "
            "needs_network, environment. The code must be self-contained executable code. "
            "Do not wrap the JSON in markdown fences."
        )
        crew_task = CrewTask(
            description=(
                f"Worker mission: {worker.mission}\n"
                f"Task description: {task.description}\n"
                f"Expected output: {task.expected_output}\n"
                f"Required tools (declarations only): {list(task.required_tools)}\n"
                "Produce an execution plan for the upstream runtime."
            ),
            expected_output=expected_output,
            agent=agent,
        )
        return Crew(agents=[agent], tasks=[crew_task], process=Process.sequential, verbose=False)

    @staticmethod
    def _result_text(result: Any) -> str:
        if isinstance(result, str):
            return result
        raw = getattr(result, "raw", None)
        if isinstance(raw, str):
            return raw
        return str(result)

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
            raise CrewAIWorkerAdapterError(f"CrewAI returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise CrewAIWorkerAdapterError("CrewAI response must be a JSON object")
        return payload
