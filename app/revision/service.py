"""State-aware revision tracking and recovery coordination."""
from __future__ import annotations

from threading import RLock
from copy import deepcopy

from app.core.states import WorkflowState
from app.session.manager import SessionManager
from app.session.models import SessionMessage

from .models import RevisionRequest


class RevisionServiceError(ValueError):
    """Raised when a revision request violates runtime recovery rules."""


class RevisionService:
    """Track revision attempts without owning planning or execution internals."""

    def __init__(self, *, session_manager: SessionManager) -> None:
        self.sessions = session_manager
        self._lock = RLock()
        self._history: dict[str, list[RevisionRequest]] = {}

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
                raise RevisionServiceError(
                    f"cannot request revision from state {state.value}"
                )

            history = self._history.setdefault(run_id, [])
            revision = RevisionRequest(
                run_id=run_id,
                reason=reason,
                source=source,
                feedback=feedback,
                attempt=len(history) + 1,
            )
            revision.validate()
            history.append(revision)

            current = self.sessions.get_context(run_id).state
            if current != WorkflowState.ARCHITECTING:
                self.sessions.transition(run_id, WorkflowState.REVISION)
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
                    "feedback": feedback,
                },
            )
            return deepcopy(revision)

    def list_revisions(self, run_id: str) -> tuple[RevisionRequest, ...]:
        with self._lock:
            return tuple(deepcopy(item) for item in self._history.get(run_id, ()))
