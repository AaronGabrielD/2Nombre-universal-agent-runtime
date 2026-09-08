"""Domain models for human approval gates."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.contracts import HumanDecisionType


class GateStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ApprovalGate:
    gate_id: str
    run_id: str
    kind: str
    title: str
    prompt: str
    context: dict[str, Any] = field(default_factory=dict)
    allowed_decisions: tuple[HumanDecisionType, ...] = (
        HumanDecisionType.APPROVE,
        HumanDecisionType.MODIFY,
        HumanDecisionType.REJECT,
        HumanDecisionType.CLARIFY,
    )
    status: GateStatus = GateStatus.OPEN
    created_at: str = ""
    resolved_at: str | None = None

    def validate(self) -> None:
        for name, value in (
            ("gate_id", self.gate_id),
            ("run_id", self.run_id),
            ("kind", self.kind),
            ("title", self.title),
            ("prompt", self.prompt),
            ("created_at", self.created_at),
        ):
            if not value.strip():
                raise ValueError(f"{name} cannot be empty")
        if not self.allowed_decisions:
            raise ValueError("allowed_decisions cannot be empty")
        if len(set(self.allowed_decisions)) != len(self.allowed_decisions):
            raise ValueError("allowed_decisions must be unique")
        if self.status == GateStatus.RESOLVED and not self.resolved_at:
            raise ValueError("resolved gates require resolved_at")
        if self.status != GateStatus.RESOLVED and self.resolved_at is not None:
            raise ValueError("only resolved gates may have resolved_at")
