"""Top-level coordination for one runtime run.

This layer coordinates existing milestone services. It does not contain UI code,
LLM provider logic, worker implementation, tool execution, or backend internals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.approval.models import GateStatus
from app.approval.service import HumanApprovalEngine
from app.architect.models import ArchitectureInput
from app.architect.service import UniversalArchitect
from app.core.contracts import ArchitecturePlan, FinalResult, HumanDecision, HumanDecisionType, to_dict
from app.core.states import WorkflowState
from app.intake.models import IntakeFile, IntakeResult
from app.intake.service import IntakeService
from app.recovery.models import RecoveryAction, RecoveryCheckpoint
from app.recovery.resume import RecoveryResumeError, RecoveryResumeResult, RecoveryResumeService
from app.revision.service import RevisionService
from app.session.manager import SessionManager
from app.supervisor.models import QAResult, QAStatus


class RuntimeCoordinatorError(ValueError):
    """Raised when a coordination operation violates the runtime lifecycle."""


@dataclass(frozen=True, slots=True)
class ArchitectureCheckpoint:
    """Result of the architecture phase before human approval."""

    run_id: str
    plan: ArchitecturePlan
    gate_id: str


class RuntimeCoordinator:
    """Coordinate the safe high-level lifecycle of a single runtime execution."""

    def __init__(
        self,
        *,
        session_manager: SessionManager | None = None,
        intake_service: IntakeService | None = None,
        architect: UniversalArchitect | None = None,
        approval_engine: HumanApprovalEngine | None = None,
        revision_service: RevisionService | None = None,
        recovery_resume_service: RecoveryResumeService | None = None,
    ) -> None:
        self.sessions = session_manager or SessionManager()
        self.intake = intake_service or IntakeService(session_manager=self.sessions)
        self.architect = architect
        self.approvals = approval_engine or HumanApprovalEngine()
        self.revisions = revision_service or RevisionService(session_manager=self.sessions)
        self.recovery_resume = recovery_resume_service or RecoveryResumeService(
            session_manager=self.sessions
        )

    def start_run(
        self,
        objective: str,
        *,
        files: tuple[IntakeFile, ...] = (),
        metadata: dict[str, str] | None = None,
        inline_text_by_name: dict[str, str] | None = None,
    ) -> IntakeResult:
        """Create and normalize a run, leaving it in INTAKE."""
        return self.intake.start_session(
            objective,
            files=files,
            metadata=metadata,
            inline_text_by_name=inline_text_by_name,
        )

    def build_architecture(
        self,
        run_id: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> ArchitectureCheckpoint:
        """Build a plan and open Gate A; execution cannot start here."""
        if self.architect is None:
            raise RuntimeCoordinatorError("No UniversalArchitect provider has been configured")

        state = self.sessions.get_context(run_id).state
        if state not in {WorkflowState.INTAKE, WorkflowState.ARCHITECTING}:
            raise RuntimeCoordinatorError(f"Cannot architect from state {state.value}")

        self.sessions.transition(run_id, WorkflowState.ARCHITECTING)
        snapshot = self.sessions.snapshot(run_id)
        objective = next(
            (
                message.content
                for message in reversed(snapshot.messages)
                if message.role == "user" and message.metadata.get("phase") == "intake"
            ),
            "",
        )
        if not objective:
            raise RuntimeCoordinatorError("Run has no intake objective")

        inputs = tuple(
            {
                "artifact_id": artifact.artifact_id,
                "name": artifact.name,
                "mime_type": artifact.mime_type,
                "uri": artifact.uri,
            }
            for artifact in snapshot.artifacts
        )
        plan = self.architect.build_plan(
            ArchitectureInput(objective=objective, inputs=inputs, context=dict(context or {}))
        )
        self.sessions.set_architecture_plan(run_id, plan)
        self.sessions.transition(run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        gate = self.approvals.request_gate(
            run_id=run_id,
            kind="ARCHITECTURE",
            title="Approve architecture plan",
            prompt=(
                "Review the proposed architecture. Approve to authorize worker execution, "
                "modify/clarify to re-plan, or reject to stop the run."
            ),
            context={"plan": to_dict(plan)},
        )
        return ArchitectureCheckpoint(run_id=run_id, plan=plan, gate_id=gate.gate_id)

    def apply_architecture_decision(self, decision: HumanDecision) -> WorkflowState:
        """Validate Gate A's recorded decision and apply it to the state machine."""
        context = self.sessions.get_context(decision.run_id)
        if context.state != WorkflowState.WAITING_ARCHITECT_APPROVAL:
            raise RuntimeCoordinatorError(
                f"Architecture decision requires WAITING_ARCHITECT_APPROVAL, got {context.state.value}"
            )
        self._validate_recorded_decision(decision)
        self.sessions.add_decision(decision.run_id, decision)

        if decision.decision == HumanDecisionType.APPROVE:
            self.sessions.transition(decision.run_id, WorkflowState.EXECUTING)
        elif decision.decision == HumanDecisionType.REJECT:
            self.sessions.transition(decision.run_id, WorkflowState.REJECTED)
        elif decision.decision in {HumanDecisionType.MODIFY, HumanDecisionType.CLARIFY}:
            self.revisions.request_revision(
                decision.run_id,
                reason=f"Architecture {decision.decision.value}",
                source="human",
                feedback=decision.feedback,
            )
        else:  # pragma: no cover - enum contract is exhaustive
            raise RuntimeCoordinatorError(f"Unsupported architecture decision: {decision.decision}")
        return self.sessions.get_context(decision.run_id).state

    def record_supervisor_result(self, result: QAResult) -> str:
        """Open Gate D only for a deterministic supervisor PASS."""
        result.validate()
        if result.status != QAStatus.PASS:
            raise RuntimeCoordinatorError("Final approval can only be requested after supervisor PASS")

        context = self.sessions.get_context(result.run_id)
        if context.state != WorkflowState.SUPERVISING:
            raise RuntimeCoordinatorError(
                f"Final approval requires SUPERVISING, got {context.state.value}"
            )

        self.sessions.transition(result.run_id, WorkflowState.WAITING_FINAL_APPROVAL)
        gate = self.approvals.request_gate(
            run_id=result.run_id,
            kind="FINAL",
            title="Approve final result",
            prompt="Supervisor passed QA. Human approval is required before this run becomes COMPLETED.",
            context={"qa_result": to_dict(result)},
            allowed_decisions=(
                HumanDecisionType.APPROVE,
                HumanDecisionType.MODIFY,
                HumanDecisionType.REJECT,
            ),
        )
        return gate.gate_id

    def apply_final_decision(
        self,
        decision: HumanDecision,
        *,
        final_result: FinalResult | None = None,
    ) -> WorkflowState:
        """Apply Gate D; only APPROVE may transition to COMPLETED."""
        context = self.sessions.get_context(decision.run_id)
        if context.state != WorkflowState.WAITING_FINAL_APPROVAL:
            raise RuntimeCoordinatorError(
                f"Final decision requires WAITING_FINAL_APPROVAL, got {context.state.value}"
            )
        if decision.decision not in {
            HumanDecisionType.APPROVE,
            HumanDecisionType.MODIFY,
            HumanDecisionType.REJECT,
        }:
            raise RuntimeCoordinatorError("Invalid decision for final approval gate")

        self._validate_recorded_decision(decision)
        self.sessions.add_decision(decision.run_id, decision)

        if decision.decision == HumanDecisionType.APPROVE:
            if final_result is None:
                final_result = FinalResult(
                    run_id=decision.run_id,
                    status="approved",
                    summary=decision.feedback or "Final result approved by human.",
                )
            if final_result.run_id != decision.run_id:
                raise RuntimeCoordinatorError("FinalResult.run_id must match the decision run_id")
            self.sessions.set_final_result(decision.run_id, final_result)
            self.sessions.transition(decision.run_id, WorkflowState.COMPLETED)
        elif decision.decision == HumanDecisionType.MODIFY:
            self.revisions.request_revision(
                decision.run_id,
                reason="Final result modification requested",
                source="human",
                feedback=decision.feedback,
            )
        else:
            self.sessions.transition(decision.run_id, WorkflowState.REJECTED)
        return self.sessions.get_context(decision.run_id).state

    def record_revision(
        self,
        run_id: str,
        *,
        reason: str,
        source: str = "runtime",
        feedback: str = "",
    ):
        """Record a recoverable revision through the canonical revision service."""
        try:
            return self.revisions.request_revision(
                run_id,
                reason=reason,
                source=source,
                feedback=feedback,
            )
        except ValueError as exc:
            raise RuntimeCoordinatorError(str(exc)) from exc

    def list_revisions(self, run_id: str):
        """Return the durable revision history for a run."""
        return self.revisions.list_revisions(run_id)

    def inspect_recovery(self, run_id: str) -> RecoveryCheckpoint:
        """Return the durable recovery checkpoint for one run."""
        try:
            return self.recovery_resume.inspect(run_id)
        except RecoveryResumeError as exc:
            raise RuntimeCoordinatorError(str(exc)) from exc

    def resume_recovery(
        self,
        *,
        run_id: str,
        action: RecoveryAction,
        idempotency_key: str | None = None,
    ) -> RecoveryResumeResult:
        """Apply one explicitly requested recovery action through the canonical service."""
        try:
            return self.recovery_resume.resume(
                run_id=run_id,
                action=action,
                idempotency_key=idempotency_key,
            )
        except RecoveryResumeError as exc:
            raise RuntimeCoordinatorError(str(exc)) from exc

    def _validate_recorded_decision(self, decision: HumanDecision) -> None:
        """Ensure a decision is exactly the immutable record produced by the gate engine."""
        gate = self.approvals.get_gate(decision.gate_id)
        if gate.run_id != decision.run_id:
            raise RuntimeCoordinatorError("Decision gate/run ownership mismatch")
        if gate.status != GateStatus.RESOLVED:
            raise RuntimeCoordinatorError("Decision must reference a resolved approval gate")
        stored = self.approvals.get_decision(decision.gate_id)
        if stored != decision:
            raise RuntimeCoordinatorError("Decision is not the recorded result of its approval gate")
