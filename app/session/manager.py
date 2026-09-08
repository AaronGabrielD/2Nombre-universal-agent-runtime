"""Public M01 API for lifecycle and isolated session state."""
from __future__ import annotations

from typing import Any

from app.core.contracts import (
    ArchitecturePlan,
    ArtifactRef,
    ExecutionResult,
    FinalResult,
    HumanDecision,
)
from app.core.models import EventRecord, RunContext
from app.core.states import WorkflowState

from .models import SessionMessage, SessionRecord, WorkerOutput
from .repository import InMemorySessionRepository, SessionRepository


class SessionManager:
    """Own one run's lifecycle and never mixes state between run_ids."""

    def __init__(self, repository: SessionRepository | None = None) -> None:
        self.repository = repository or InMemorySessionRepository()

    def create_session(self, *, metadata: dict[str, str] | None = None) -> RunContext:
        context = RunContext(metadata=dict(metadata or {}))
        self.repository.create(SessionRecord(context=context))
        return context

    def destroy_session(self, run_id: str) -> None:
        self.repository.delete(run_id)

    def get_context(self, run_id: str) -> RunContext:
        return self.repository.get(run_id).context

    def transition(self, run_id: str, target: WorkflowState) -> RunContext:
        record = self.repository.get(run_id)
        record.context.transition_to(target)
        return record.context

    def add_message(
        self,
        run_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionMessage:
        self._require_nonempty(content, "content")
        if not role.strip():
            raise ValueError("role cannot be empty")
        message = SessionMessage(
            run_id=run_id,
            role=role,
            content=content,
            metadata=dict(metadata or {}),
        )
        self.repository.get(run_id).messages.append(message)
        return message

    def add_artifact(self, run_id: str, artifact: ArtifactRef) -> None:
        self.repository.get(run_id).artifacts.append(artifact)

    def add_decision(self, run_id: str, decision: HumanDecision) -> None:
        if decision.run_id != run_id:
            raise ValueError("HumanDecision.run_id must match the target session")
        self.repository.get(run_id).decisions.append(decision)

    def add_execution_result(self, run_id: str, result: ExecutionResult) -> None:
        self.repository.get(run_id).execution_results.append(result)

    def set_architecture_plan(self, run_id: str, plan: ArchitecturePlan) -> None:
        self.repository.get(run_id).architecture_plan = plan

    def set_worker_output(self, run_id: str, output: WorkerOutput) -> None:
        if output.run_id != run_id:
            raise ValueError("WorkerOutput.run_id must match the target session")
        self.repository.get(run_id).worker_outputs[output.worker_id] = output

    def set_final_result(self, run_id: str, result: FinalResult) -> None:
        if result.run_id != run_id:
            raise ValueError("FinalResult.run_id must match the target session")
        self.repository.get(run_id).final_result = result

    def snapshot(self, run_id: str) -> SessionRecord:
        """Return the session record for inspection by orchestration layers."""
        return self.repository.get(run_id)

    @staticmethod
    def event_for(run_id: str, *, event_type: str, message: str, status: str = "info") -> EventRecord:
        return EventRecord(
            run_id=run_id,
            component="session_manager",
            event_type=event_type,
            status=status,
            short_message=message,
        )

    @staticmethod
    def _require_nonempty(value: str, field_name: str) -> None:
        if not value.strip():
            raise ValueError(f"{field_name} cannot be empty")
