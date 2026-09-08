"""Session-scoped records used by M01 without provider-specific dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

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
    architecture_plan: ArchitecturePlan | None = None
    final_result: FinalResult | None = None
