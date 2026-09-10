"""UI-neutral human approval gate service."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from typing import Any, TYPE_CHECKING
import uuid

from app.core.contracts import HumanDecision, HumanDecisionType

from .models import ApprovalGate, GateStatus

if TYPE_CHECKING:
    from app.session.manager import SessionManager


class ApprovalError(ValueError):
    """Raised when an approval operation violates gate invariants."""


class HumanApprovalEngine:
    """Owns approval-gate lifecycle and immutable decision history.

    When a ``SessionManager`` is supplied, gates and their decisions are
    restored from the durable run records before the engine accepts requests.
    """

    def __init__(self, session_manager: SessionManager | None = None) -> None:
        self._gates: dict[str, ApprovalGate] = {}
        self._decisions: dict[str, tuple[HumanDecision, ...]] = {}
        self._session_manager = session_manager
        self._lock = RLock()
        if session_manager is not None:
            self._hydrate(session_manager)

    def _hydrate(self, session_manager: SessionManager) -> None:
        try:
            sessions = session_manager.list_sessions()
        except Exception as exc:
            raise ApprovalError("failed to restore durable approval gates") from exc

        for session in sessions:
            for gate in getattr(session, "approval_gates", []):
                try:
                    gate.validate()
                except (AttributeError, ValueError) as exc:
                    raise ApprovalError(f"invalid persisted gate: {getattr(gate, 'gate_id', '<unknown>')}") from exc
                if gate.run_id != session.context.run_id:
                    raise ApprovalError(f"persisted gate {gate.gate_id} belongs to another run")
                if gate.gate_id in self._gates:
                    raise ApprovalError(f"duplicate persisted gate: {gate.gate_id}")
                history = tuple(
                    decision
                    for decision in session.decisions
                    if decision.gate_id == gate.gate_id
                )
                for decision in history:
                    if decision.run_id != gate.run_id:
                        raise ApprovalError(f"persisted decision for gate {gate.gate_id} belongs to another run")
                    try:
                        decision.validate()
                    except Exception as exc:
                        raise ApprovalError(f"invalid persisted decision for gate {gate.gate_id}") from exc
                if gate.status == GateStatus.OPEN and history:
                    raise ApprovalError(f"open persisted gate {gate.gate_id} already has a decision")
                if gate.status == GateStatus.RESOLVED and len(history) != 1:
                    raise ApprovalError(f"resolved persisted gate {gate.gate_id} must have exactly one decision")
                if gate.status == GateStatus.CANCELLED and history:
                    raise ApprovalError(f"cancelled persisted gate {gate.gate_id} cannot have a decision")
                self._gates[gate.gate_id] = _copy_gate(gate)
                self._decisions[gate.gate_id] = history

    def request_gate(
        self,
        *,
        run_id: str,
        kind: str,
        title: str,
        prompt: str,
        context: dict[str, Any] | None = None,
        allowed_decisions: tuple[HumanDecisionType, ...] | None = None,
        gate_id: str | None = None,
    ) -> ApprovalGate:
        now = _utc_now()
        gate = ApprovalGate(
            gate_id=gate_id or f"gate-{uuid.uuid4().hex}",
            run_id=run_id,
            kind=kind,
            title=title,
            prompt=prompt,
            context=deepcopy(context or {}),
            allowed_decisions=allowed_decisions or (
                HumanDecisionType.APPROVE,
                HumanDecisionType.MODIFY,
                HumanDecisionType.REJECT,
                HumanDecisionType.CLARIFY,
            ),
            created_at=now,
        )
        try:
            gate.validate()
        except ValueError as exc:
            raise ApprovalError(str(exc)) from exc
        with self._lock:
            if gate.gate_id in self._gates:
                raise ApprovalError(f"gate {gate.gate_id} already exists")
            if self._session_manager is not None:
                try:
                    self._session_manager.add_approval_gate(run_id, gate)
                except Exception as exc:
                    raise ApprovalError(f"failed to persist gate {gate.gate_id}") from exc
            self._gates[gate.gate_id] = gate
            self._decisions[gate.gate_id] = ()
        return _copy_gate(gate)

    def get_gate(self, gate_id: str) -> ApprovalGate:
        with self._lock:
            gate = self._gates.get(gate_id)
            if gate is None:
                raise ApprovalError(f"unknown gate: {gate_id}")
            return _copy_gate(gate)

    def list_open_gates(self, *, run_id: str | None = None) -> tuple[ApprovalGate, ...]:
        with self._lock:
            gates = [gate for gate in self._gates.values() if gate.status == GateStatus.OPEN]
            if run_id is not None:
                gates = [gate for gate in gates if gate.run_id == run_id]
            return tuple(_copy_gate(gate) for gate in gates)

    def list_gates(
        self,
        *,
        run_id: str | None = None,
        kind: str | None = None,
    ) -> tuple[ApprovalGate, ...]:
        """List immutable gate snapshots, optionally filtered by run and kind."""
        with self._lock:
            gates = list(self._gates.values())
            if run_id is not None:
                gates = [gate for gate in gates if gate.run_id == run_id]
            if kind is not None:
                gates = [gate for gate in gates if gate.kind == kind]
            return tuple(_copy_gate(gate) for gate in gates)

    def resolve_gate(
        self,
        *,
        gate_id: str,
        decision: HumanDecisionType,
        feedback: str,
        actor: str = "human",
        timestamp: str | None = None,
    ) -> HumanDecision:
        if not isinstance(decision, HumanDecisionType):
            try:
                decision = HumanDecisionType(decision)
            except (ValueError, TypeError) as exc:
                raise ApprovalError(f"invalid decision: {decision!r}") from exc
        if not isinstance(feedback, str):
            raise ApprovalError("feedback must be a string")
        if not isinstance(actor, str) or not actor.strip():
            raise ApprovalError("actor cannot be empty")
        resolved_at = timestamp or _utc_now()
        with self._lock:
            gate = self._gates.get(gate_id)
            if gate is None:
                raise ApprovalError(f"unknown gate: {gate_id}")
            if gate.status != GateStatus.OPEN:
                raise ApprovalError(f"gate {gate_id} is already {gate.status.value}")
            if decision not in gate.allowed_decisions:
                allowed = ", ".join(item.value for item in gate.allowed_decisions)
                raise ApprovalError(
                    f"decision {decision.value!r} is not allowed for gate {gate_id}; allowed: {allowed}"
                )
            record = HumanDecision(
                gate_id=gate.gate_id,
                run_id=gate.run_id,
                decision=decision,
                feedback=feedback.strip(),
                timestamp=resolved_at,
                actor=actor.strip(),
            )
            resolved_gate = replace(gate, status=GateStatus.RESOLVED, resolved_at=resolved_at)
            if self._session_manager is not None:
                try:
                    self._session_manager.resolve_approval_gate(gate.run_id, resolved_gate, record)
                except Exception as exc:
                    raise ApprovalError(f"failed to persist resolution for gate {gate_id}") from exc
            self._decisions[gate_id] = self._decisions[gate_id] + (record,)
            self._gates[gate_id] = resolved_gate
            return record

    def cancel_gate(self, gate_id: str) -> ApprovalGate:
        with self._lock:
            gate = self._gates.get(gate_id)
            if gate is None:
                raise ApprovalError(f"unknown gate: {gate_id}")
            if gate.status != GateStatus.OPEN:
                raise ApprovalError(f"gate {gate_id} is already {gate.status.value}")
            cancelled = replace(gate, status=GateStatus.CANCELLED)
            if self._session_manager is not None:
                try:
                    self._session_manager.cancel_approval_gate(gate.run_id, cancelled)
                except Exception as exc:
                    raise ApprovalError(f"failed to persist cancellation for gate {gate_id}") from exc
            self._gates[gate_id] = cancelled
            return _copy_gate(cancelled)

    def get_decision(self, gate_id: str) -> HumanDecision | None:
        history = self.get_decision_history(gate_id)
        return history[-1] if history else None

    def get_decision_history(self, gate_id: str) -> tuple[HumanDecision, ...]:
        with self._lock:
            if gate_id not in self._gates:
                raise ApprovalError(f"unknown gate: {gate_id}")
            return tuple(self._decisions[gate_id])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_gate(gate: ApprovalGate) -> ApprovalGate:
    return replace(gate, context=deepcopy(gate.context))
