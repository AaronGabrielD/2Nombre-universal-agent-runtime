"""Provider-neutral Universal Architect orchestration."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.core.contracts import ArchitecturePlan, WorkerSpec
from app.core.config import Settings, get_settings
from app.llm.interfaces import GenerationRequest, LLMProvider

from .models import ArchitectureInput


class ArchitectPlanningError(ValueError):
    """Raised when the LLM response cannot become a valid architecture plan."""


_SYSTEM_PROMPT = """You are the Universal Architect of a domain-agnostic multi-agent runtime.

Your job is ONLY to design an executable architecture plan. Do not execute tasks, call tools,
write implementation code, or claim that work was performed. Do not reveal private chain-of-thought.
Return only one JSON object matching the required schema.

Schema:
{
  \"plan_id\": string,
  \"objective\": string,
  \"assumptions\": [string],
  \"constraints\": [string],
  \"acceptance_criteria\": [string],
  \"risks\": [string],
  \"required_capabilities\": [string],
  \"workers\": [
    {
      \"worker_id\": string,
      \"role\": string,
      \"mission\": string,
      \"deliverables\": [string],
      \"required_tools\": [string],
      \"dependencies\": [string],
      \"can_request_human_input\": boolean
    }
  ]
}

Planning rules:
- Keep the design domain-agnostic and grounded in the supplied objective and inputs.
- Prefer 3 workers when there is meaningful parallel work; use fewer only when the work is inherently sequential.
- Never exceed the configured worker limit.
- Worker IDs must be unique and dependencies must reference existing worker IDs.
- Required tools/capabilities are declarations only; availability is decided elsewhere.
- Make acceptance criteria concrete and testable.
- Identify meaningful assumptions, constraints, risks, and dependencies.
- The human remains the final authority; do not assume approval has been granted.
"""


class UniversalArchitect:
    """Build and validate ArchitecturePlan objects using an injected LLM provider."""

    def __init__(self, provider: LLMProvider, settings: Settings | None = None) -> None:
        self._provider = provider
        self._settings = settings or get_settings()

    def build_plan(self, request: ArchitectureInput) -> ArchitecturePlan:
        request.validate()
        payload = json.dumps(request.to_prompt_payload(), ensure_ascii=False, default=str)
        generation = self._provider.generate(
            GenerationRequest(
                model=self._settings.gemini_model_architect,
                contents=payload,
                system_instruction=_SYSTEM_PROMPT,
                temperature=min(self._settings.gemini_temperature, 0.2),
                metadata={"component": "universal_architect"},
            )
        )
        try:
            data = _decode_json_object(generation.text)
            plan = _plan_from_dict(data)
            plan.validate(max_workers=self._settings.max_workers)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ArchitectPlanningError(f"Invalid architecture plan: {exc}") from exc
        return plan


def _decode_json_object(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("empty model response")
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    data = json.loads(candidate)
    if not isinstance(data, dict):
        raise ValueError("top-level JSON value must be an object")
    return data


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise TypeError(f"{field_name} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _plan_from_dict(data: dict[str, Any]) -> ArchitecturePlan:
    workers_raw = data.get("workers")
    if not isinstance(workers_raw, list) or not workers_raw:
        raise ValueError("workers must be a non-empty list")

    workers: list[WorkerSpec] = []
    for raw in workers_raw:
        if not isinstance(raw, dict):
            raise TypeError("each worker must be an object")
        human_input = raw.get("can_request_human_input", True)
        if not isinstance(human_input, bool):
            raise TypeError("can_request_human_input must be boolean")
        workers.append(
            WorkerSpec(
                worker_id=_required_str(raw, "worker_id"),
                role=_required_str(raw, "role"),
                mission=_required_str(raw, "mission"),
                deliverables=_strings(raw.get("deliverables"), "deliverables"),
                required_tools=_strings(raw.get("required_tools"), "required_tools"),
                dependencies=_strings(raw.get("dependencies"), "dependencies"),
                can_request_human_input=human_input,
            )
        )

    plan_id = data.get("plan_id") or f"plan-{uuid.uuid4().hex}"
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise ValueError("plan_id must be a non-empty string")

    return ArchitecturePlan(
        plan_id=plan_id.strip(),
        objective=_required_str(data, "objective"),
        assumptions=_strings(data.get("assumptions"), "assumptions"),
        constraints=_strings(data.get("constraints"), "constraints"),
        acceptance_criteria=_strings(data.get("acceptance_criteria"), "acceptance_criteria"),
        risks=_strings(data.get("risks"), "risks"),
        required_capabilities=_strings(data.get("required_capabilities"), "required_capabilities"),
        workers=tuple(workers),
    )
