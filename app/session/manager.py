"""Public M01 API for lifecycle and isolated session state."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any

from app.approval.models import ApprovalGate, GateStatus
from app.core.contracts import ArchitecturePlan, ArtifactRef, ExecutionResult, FinalResult, HumanDecision
from app.core.models import EventRecord, RunContext
from app.core.states import TERMINAL_STATES, WorkflowState
from .models import SessionMessage, SessionRecord, WorkerOutput
from .repository import InMemorySessionRepository, SessionRepository


class SessionManager:
    """Own one run's lifecycle and serialize all mutable session operations."""

    def __init__(self, repository: SessionRepository | None = None) -> None:
        self.repository = repository or InMemorySessionRepository()
        self._lock = RLock()

    def create_session(self, *, metadata: dict[str, str] | None = None) -> RunContext:
        context = RunContext(metadata=dict(metadata or {}))
        with self._lock:
            self.repository.create(SessionRecord(context=context))
            return deepcopy(context)

    def destroy_session(self, run_id: str) -> None:
        with self._lock:
            self.repository.delete(run_id)

    def get_context(self, run_id: str) -> RunContext:
        with self._lock:
            return deepcopy(self.repository.get(run_id).context)

    def list_sessions(self) -> tuple[SessionRecord, ...]:
        with self._lock:
            return tuple(deepcopy(record) for record in self.repository.list())

    def list_recoverable_sessions(self) -> tuple[SessionRecord, ...]:
        with self._lock:
            return tuple(deepcopy(record) for record in self.repository.list() if record.context.state not in TERMINAL_STATES)

    def transition(self, run_id: str, target: WorkflowState) -> RunContext:
        with self._lock:
            record = self.repository.get(run_id)
            record.context.transition_to(target)
            self.repository.save(record)
            return deepcopy(record.context)

    def add_message(self, run_id: str, *, role: str, content: str, metadata: dict[str, Any] | None = None) -> SessionMessage:
        self._require_nonempty(content, "content")
        if not isinstance(role, str) or not role.strip():
            raise ValueError("role cannot be empty")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a mapping")
        message = SessionMessage(run_id=run_id, role=role, content=content, metadata=deepcopy(metadata or {}))
        with self._lock:
            record = self.repository.get(run_id)
            record.messages.append(message)
            self.repository.save(record)
        return deepcopy(message)

    def add_artifact(self, run_id: str, artifact: ArtifactRef) -> None:
        artifact.validate()
        with self._lock:
            record = self.repository.get(run_id)
            if any(existing.artifact_id == artifact.artifact_id for existing in record.artifacts):
                raise ValueError(f"artifact already exists: {artifact.artifact_id}")
            record.artifacts.append(deepcopy(artifact))
            self.repository.save(record)

    def add_decision(self, run_id: str, decision: HumanDecision) -> None:
        decision.validate()
        if decision.run_id != run_id:
            raise ValueError("HumanDecision.run_id must match the target session")
        with self._lock:
            record = self.repository.get(run_id)
            for existing in record.decisions:
                if existing == decision:
                    return
                if existing.gate_id == decision.gate_id:
                    raise ValueError(f"decision already exists for gate {decision.gate_id}")
            record.decisions.append(deepcopy(decision))
            self.repository.save(record)

    def add_execution_result(self, run_id: str, result: ExecutionResult) -> None:
        result.validate()
        if result.run_id != run_id:
            raise ValueError("ExecutionResult.run_id must match the target session")
        with self._lock:
            record = self.repository.get(run_id)
            existing = next((item for item in record.execution_results if item.execution_id == result.execution_id), None)
            if existing is not None:
                if existing != result:
                    raise ValueError(f"conflicting execution result: {result.execution_id}")
                return
            record.execution_results.append(deepcopy(result))
            self.repository.save(record)

    def add_approval_gate(self, run_id: str, gate: ApprovalGate) -> ApprovalGate:
        gate.validate()
        if gate.run_id != run_id:
            raise ValueError("ApprovalGate.run_id must match the target session")
        with self._lock:
            record = self.repository.get(run_id)
            if any(existing.gate_id == gate.gate_id for existing in record.approval_gates):
                raise ValueError(f"gate {gate.gate_id} already exists")
            record.approval_gates.append(deepcopy(gate))
            self.repository.save(record)
        return deepcopy(gate)

    def resolve_approval_gate(self, run_id: str, gate: ApprovalGate, decision: HumanDecision) -> ApprovalGate:
        gate.validate()
        decision.validate()
        if gate.run_id != run_id or decision.run_id != run_id or decision.gate_id != gate.gate_id:
            raise ValueError("approval gate and decision must match the target session")
        if gate.status != GateStatus.RESOLVED:
            raise ValueError("resolved approval gate required")
        with self._lock:
            record = self.repository.get(run_id)
            index = next((i for i, existing in enumerate(record.approval_gates) if existing.gate_id == gate.gate_id), None)
            if index is None:
                raise ValueError(f"unknown gate: {gate.gate_id}")
            existing = record.approval_gates[index]
            if existing.status != GateStatus.OPEN:
                raise ValueError(f"gate {gate.gate_id} is already {existing.status.value}")
            if any(item.gate_id == decision.gate_id for item in record.decisions):
                raise ValueError(f"decision already exists for gate {gate.gate_id}")
            record.approval_gates[index] = deepcopy(gate)
            record.decisions.append(deepcopy(decision))
            self.repository.save(record)
        return deepcopy(gate)

    def cancel_approval_gate(self, run_id: str, gate: ApprovalGate) -> ApprovalGate:
        gate.validate()
        if gate.run_id != run_id or gate.status != GateStatus.CANCELLED:
            raise ValueError("cancelled approval gate must match the target session")
        with self._lock:
            record = self.repository.get(run_id)
            index = next((i for i, existing in enumerate(record.approval_gates) if existing.gate_id == gate.gate_id), None)
            if index is None:
                raise ValueError(f"unknown gate: {gate.gate_id}")
            if record.approval_gates[index].status != GateStatus.OPEN:
                raise ValueError(f"gate {gate.gate_id} is already {record.approval_gates[index].status.value}")
            record.approval_gates[index] = deepcopy(gate)
            self.repository.save(record)
        return deepcopy(gate)

    def set_architecture_plan(self, run_id: str, plan: ArchitecturePlan) -> None:
        plan.validate()
        with self._lock:
            record = self.repository.get(run_id)
            record.architecture_plan = deepcopy(plan)
            self.repository.save(record)

    def set_worker_output(self, run_id: str, output: WorkerOutput) -> None:
        output.validate()
        if output.run_id != run_id:
            raise ValueError("WorkerOutput.run_id must match the target session")
        with self._lock:
            record = self.repository.get(run_id)
            record.worker_outputs[output.worker_id] = deepcopy(output)
            self.repository.save(record)

    def set_final_result(self, run_id: str, result: FinalResult) -> None:
        result.validate()
        if result.run_id != run_id:
            raise ValueError("FinalResult.run_id must match the target session")
        with self._lock:
            record = self.repository.get(run_id)
            record.final_result = deepcopy(result)
            self.repository.save(record)

    def snapshot(self, run_id: str) -> SessionRecord:
        with self._lock:
            return deepcopy(self.repository.get(run_id))

    @staticmethod
    def event_for(run_id: str, *, event_type: str, message: str, status: str = "info") -> EventRecord:
        return EventRecord(run_id=run_id, component="session_manager", event_type=event_type, status=status, short_message=message)

    @staticmethod
    def _require_nonempty(value: str, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} cannot be empty")
