"""Composition-level recovery facade (M41)."""
from __future__ import annotations

from app.recovery.models import RecoveryAction, RecoveryCheckpoint
from app.recovery.resume import RecoveryResumeResult, RecoveryResumeService
from app.session.manager import SessionManager


class RuntimeRecoveryFacade:
    """Expose recovery inspection and explicit resume through one runtime-owned boundary."""

    def __init__(self, *, session_manager: SessionManager) -> None:
        self.service = RecoveryResumeService(session_manager=session_manager)

    def inspect(self, run_id: str) -> RecoveryCheckpoint:
        return self.service.inspect(run_id)

    def list_checkpoints(self) -> tuple[RecoveryCheckpoint, ...]:
        return self.service.recovery.list_checkpoints()

    def resume(
        self,
        *,
        run_id: str,
        action: RecoveryAction,
        idempotency_key: str | None = None,
    ) -> RecoveryResumeResult:
        return self.service.resume(
            run_id=run_id,
            action=action,
            idempotency_key=idempotency_key,
        )
