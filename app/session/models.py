"""Session-scoped records used by M01 without provider-specific dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from app.approval.models import ApprovalGate
from app.core.contracts import (
    ArchitecturePlan,
    ArtifactRef,
    ExecutionResult,
    FinalResult,
    HumanDecision,
)
from app.core.models import RunContext


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class SessionMessage:
    message_id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str = ""
    role: str = "user"
    content: str = ""
    timestamp: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkerOutput:
    worker_id: str
    run_id: str
    status: str
    output: Any = None
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class SessionRecord:
    """All mutable state belonging to exactly one run_id."""

    context: RunContext
    messages: list[SessionMessage] = field(default_factory=list)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    decisions: list[HumanDecision] = field(default_factory=list)
    execution_results: list[ExecutionResult] = field(default_factory=list)
    worker_outputs: dict[str, WorkerOutput] = field(default_factory=dict)
    approval_gates: list[ApprovalGate] = field(default_factory=list)
    architecture_plan: ArchitecturePlan | None = None
    final_result: FinalResult | None = None

    def __setstate__(self, state: object) -> None:
        """Backfill the gate collection when loading pre-gate-persistence pickles."""
        if isinstance(state, tuple) and len(state) == 2 and isinstance(state[1], dict):
            state = state[1]
        if not isinstance(state, dict):
            raise TypeError("invalid SessionRecord pickle state")
        for field_name, value in state.items():
            object.__setattr__(self, field_name, value)
        if not hasattr(self, "approval_gates"):
            object.__setattr__(self, "approval_gates", [])
