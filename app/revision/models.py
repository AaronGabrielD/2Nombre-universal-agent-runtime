"""Provider-neutral revision records for recoverable runtime runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class RevisionRequest:
    """One explicit request to rework a run before it can continue."""

    revision_id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str = ""
    reason: str = ""
    source: str = "runtime"
    feedback: str = ""
    attempt: int = 1
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def validate(self) -> None:
        if not self.revision_id.strip():
            raise ValueError("revision_id cannot be empty")
        if not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not self.reason.strip():
            raise ValueError("reason cannot be empty")
        if not self.source.strip():
            raise ValueError("source cannot be empty")
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")
