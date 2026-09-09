"""State-aware revision tracking and recovery coordination."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock

from app.core.states import WorkflowState
from app.session.manager import SessionManager

from .models import RevisionRequest


class RevisionServiceError(ValueError):
    """Raised when a revision request violates runtime recovery rules."""


class RevisionService:
    """Track recoverable revision records in the durable session history."""

    def __init__(self, *, session_manager: SessionManager) -> None:
        self.sessions = session_manager
        self._lock = RLock()

    def request_revision(
        self,
        run_id: str,
        *,
        reason: str,
        source: str = "runtime",
        feedback: str = "",
    ) -> RevisionRequest:
        """Record a revision and move the run into the ARCHITECTING phase."""
        reason = reason.strip()
        source = source.strip()
        if not reason:
            raise RevisionServiceError("revision reason cannot be empty")
        if not source:
            raise RevisionServiceError("revision source cannot be empty")

        with self._lock:
            state = self.sessions.get_context(run_id).state
            if state not in {
                WorkflowState.REVISION,
                WorkflowState.SUPERVISING,
                WorkflowState.WAITING_FINAL_APPROVAL,
            }:
                raise RevisionServiceError(f"cannot request revision from state {state.value}")

            snapshot = self.sessions.snapshot(run_id)
            attempt = 1 + sum(
                1
                for message in snapshot.messages
                if message.metadata.get("phase") == "revision"
            )
            revision = RevisionRequest(
                run_id=run_id,
                reason=reason,
                source=source,
                feedback=feedback,
                attempt=attempt,
            )
            revision.validate()

            current = self.sessions.get_context(run_id).state
            if current in {WorkflowState.SUPERVISING, WorkflowState.WAITING_FINAL_APPROVAL}:
                self.sessions.transition(run_id, WorkflowState.REVISION)
                current = WorkflowState.REVISION
            if current == WorkflowState.REVISION:
                self.sessions.transition(run_id, WorkflowState.ARCHITECTING)

            self.sessions.add_message(
                run_id,
                role="system",
                content=f"Revision requested ({revision.attempt}) by {source}: {reason}",
                metadata={
                    "phase": "revision",
                    "revision_id": revision.revision_id,
                    "attempt": revision.attempt,
                    "source": source,
                    "reason": reason,
                    "feedback": feedback,
                    "timestamp": revision.timestamp,
                },
            )
            return deepcopy(revision)

    def list_revisions(self, run_id: str) -> tuple[RevisionRequest, ...]:
        """Reconstruct revision history from persisted session messages."""
        with self._lock:
            snapshot = self.sessions.snapshot(run_id)
            revisions: list[RevisionRequest] = []
            for message in snapshot.messages:
                metadata = message.metadata
                if metadata.get("phase") != "revision":
                    continue
                revision = RevisionRequest(
                    revision_id=str(metadata.get("revision_id") or ""),
                    run_id=run_id,
                    reason=str(metadata.get("reason") or ""),
                    source=str(metadata.get("source") or "runtime"),
                    feedback=str(metadata.get("feedback") or ""),
                    attempt=int(metadata.get("attempt") or 0),
                    timestamp=str(metadata.get("timestamp") or message.timestamp),
                )
                revision.validate()
                revisions.append(revision)
            return tuple(deepcopy(revisions))
