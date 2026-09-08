"""UI-neutral human approval gate service."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from typing import Any
import uuid

from app.core.contracts import HumanDecision, HumanDecisionType

from .models import ApprovalGate, GateStatus


class ApprovalError(ValueError):
    """Raised when an approval operation violates gate invariants."""


class HumanApprovalEngine:
    """Owns approval-gate lifecycle and immutable decision history.

    The engine deliberately has no UI, Chainlit, LLM, or execution dependencies.
    Callers may poll `get_gate()` or subscribe externally and present the open
    gate through any interface.
    """

    def __init__(self) -> None:
        self._gates: dict[str, ApprovalGate] = {}
        self._decisions: dict[str, tuple[HumanDecision, ...]] = {}
        self._lock = RLock()

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
        """Create an open gate and return an immutable snapshot."""
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
        gate.validate()
        with self._lock:
            if gate.gate_id in self._gates:
                raise ApprovalError(f"gate {gate.gate_id} already exists")
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

    def resolve_gate(
        self,
        *,
        gate_id: str,
        decision: HumanDecisionType,
        feedback: str,
        actor: str = "human",
        timestamp: str | None = None,
    ) -> HumanDecision:
        """Resolve an open gate exactly once and append an immutable audit record."""
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
            self._decisions[gate_id] = self._decisions[gate_id] + (record,)
            self._gates[gate_id] = replace(gate, status=GateStatus.RESOLVED, resolved_at=resolved_at)
            return record

    def cancel_gate(self, gate_id: str) -> ApprovalGate:
        """Cancel an open gate without inventing a human decision."""
        with self._lock:
            gate = self._gates.get(gate_id)
            if gate is None:
                raise ApprovalError(f"unknown gate: {gate_id}")
            if gate.status != GateStatus.OPEN:
                raise ApprovalError(f"gate {gate_id} is already {gate.status.value}")
            cancelled = replace(gate, status=GateStatus.CANCELLED)
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
