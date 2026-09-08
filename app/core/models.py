"""Runtime domain models that are not provider-specific contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from .states import WorkflowState, ensure_transition


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class RunContext:
    """Mutable state isolated to one user execution."""

    run_id: str = field(default_factory=lambda: str(uuid4()))
    state: WorkflowState = WorkflowState.IDLE
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, str] = field(default_factory=dict)

    def transition_to(self, target: WorkflowState) -> None:
        ensure_transition(self.state, target)
        self.state = target
        self.updated_at = utc_now()


@dataclass(frozen=True, slots=True)
class EventRecord:
    """Structured operational event; deliberately excludes secret values."""

    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=utc_now)
    run_id: str = ""
    component: str = "runtime"
    event_type: str = "runtime.event"
    status: str = "info"
    short_message: str = ""
    agent_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
