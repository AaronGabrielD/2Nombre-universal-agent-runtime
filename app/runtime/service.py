"""Top-level coordination for one runtime run."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any

from app.approval.models import GateStatus
from app.approval.service import HumanApprovalEngine
from app.architect.models import ArchitectureInput
from app.architect.service import UniversalArchitect
from app.core.contracts import (
    ArchitecturePlan,
    FinalResult,
    HumanDecision,
    HumanDecisionType,
    to_dict,
)
from app.core.states import WorkflowState
from app.intake.models import IntakeFile, IntakeResult
from app.intake.service import IntakeService
from app.recovery.models import RecoveryAction
from app.recovery.resume import RecoveryResumeError, RecoveryResumeService
from app.revision.service import RevisionService
from app.session.manager import SessionManager
from app.supervisor.models import QAResult, QAStatus, SupervisorInput
from app.supervisor.service import SupervisorService


class RuntimeCoordinatorError(ValueError):
    """Raised when a top-level runtime transition violates an invariant."""


@dataclass(frozen=True, slots=True)
class ArchitectureCheckpoint:
    run_id: str
    plan: ArchitecturePlan
    gate_id: str


class RuntimeCoordinator:
    def __init__(
        self,
        *,
        session_manager=None,
        intake_service=None,
        architect=None,
        approval_engine=None,
        revision_service=None,
        recovery_resume_service=None,
        supervisor=None,
    ):
        self.sessions = session_manager or SessionManager()
        self.intake = intake_service or IntakeService(session_manager=self.sessions)
        self.architect = architect
        self.approvals = approval_engine or HumanApprovalEngine()
        self.revisions = revision_service or RevisionService(session_manager=self.sessions)
        self.recovery_resume = recovery_resume_service or RecoveryResumeService(
            session_manager=self.sessions
        )
        self.supervisor = supervisor or SupervisorService()

    def start_run(
        self,
        objective: str,
        *,
        files: tuple[IntakeFile, ...] = (),
        metadata: dict[str, str] | None = None,
        inline_text_by_name: dict[str, str] | None = None,
    ) -> IntakeResult:
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
        if self.architect is None:
            raise RuntimeCoordinatorError(
                "No UniversalArchitect provider has been configured"
            )
        state = self.sessions.get_context(run_id).state
        if state not in {WorkflowState.INTAKE, WorkflowState.ARCHITECTING}:
            raise RuntimeCoordinatorError(
                f"Cannot architect from state {state.value}"
            )
        if state == WorkflowState.INTAKE:
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
        plan = self.architect.build_plan(
            ArchitectureInput(
                objective=objective,
                inputs=tuple(
                    {
                        "artifact_id": artifact.artifact_id,
                        "name": artifact.name,
                        "mime_type": artifact.mime_type,
                        "uri": artifact.uri,
                    }
                    for artifact in snapshot.artifacts
                ),
                context=dict(context or {}),
            )
        )
        self.sessions.set_architecture_plan(run_id, plan)
        self.sessions.transition(run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        gate = self.approvals.request_gate(
            run_id=run_id,
            kind="ARCHITECTURE",
            title="Approve architecture plan",
            prompt=(
                "Review the proposed architecture. Approve to authorize worker "
                "execution, modify/clarify to re-plan, or reject to stop the run."
            ),
            context={"plan": to_dict(plan)},
        )
        return ArchitectureCheckpoint(run_id, plan, gate.gate_id)

    def apply_architecture_decision(self, decision):
        if (
            self.sessions.get_context(decision.run_id).state
            != WorkflowState.WAITING_ARCHITECT_APPROVAL
        ):
            raise RuntimeCoordinatorError(
                "Architecture decision requires WAITING_ARCHITECT_APPROVAL"
            )
        self._validate_recorded_decision(decision)
        self.sessions.add_decision(decision.run_id, decision)
        if decision.decision == HumanDecisionType.APPROVE:
            self.sessions.transition(decision.run_id, WorkflowState.EXECUTING)
        elif decision.decision == HumanDecisionType.REJECT:
            self.sessions.transition(decision.run_id, WorkflowState.REJECTED)
        elif decision.decision in {
            HumanDecisionType.MODIFY,
            HumanDecisionType.CLARIFY,
        }:
            self.revisions.request_revision(
                decision.run_id,
                reason=f"Architecture {decision.decision.value}",
                source="human",
                feedback=decision.feedback,
            )
        else:
            raise RuntimeCoordinatorError(
                f"Unsupported architecture decision: {decision.decision}"
            )
        return self.sessions.get_context(decision.run_id).state

    def record_supervisor_result(self, result: QAResult) -> str:
        result.validate()
        if result.status != QAStatus.PASS:
            raise RuntimeCoordinatorError(
                "Only a supervisor PASS can open final approval"
            )
        if self.sessions.get_context(result.run_id).state != WorkflowState.SUPERVISING:
            raise RuntimeCoordinatorError(
                "Final approval requires a supervisor PASS while SUPERVISING"
            )
        evidence_hash = _qa_hash(result)
        snapshot = self.sessions.snapshot(result.run_id)
        latest_qa = _latest_qa_message(snapshot.messages)
        if latest_qa is not None and latest_qa != evidence_hash:
            raise RuntimeCoordinatorError(
                "Supervisor result does not match the latest persisted QA evidence"
            )
        self.sessions.add_message(
            result.run_id,
            role="supervisor",
            content=result.summary,
            metadata={
                "phase": "qa",
                "qa_result": to_dict(result),
                "evidence_hash": evidence_hash,
            },
        )
        self.sessions.transition(result.run_id, WorkflowState.WAITING_FINAL_APPROVAL)
        gate = self.approvals.request_gate(
            run_id=result.run_id,
            kind="FINAL",
            title="Approve final result",
            prompt=(
                "Supervisor passed QA. Human approval is required before this "
                "run becomes COMPLETED."
            ),
            context={"qa_result": to_dict(result), "evidence_hash": evidence_hash},
        )
        return gate.gate_id

    def apply_final_decision(self, decision, *, final_result=None):
        if (
            self.sessions.get_context(decision.run_id).state
            != WorkflowState.WAITING_FINAL_APPROVAL
        ):
            raise RuntimeCoordinatorError(
                "Final decision requires WAITING_FINAL_APPROVAL"
            )
        self._validate_recorded_decision(decision)
        gate = self.approvals.get_gate(decision.gate_id)
        if gate.kind != "FINAL":
            raise RuntimeCoordinatorError("Finalization requires the resolved FINAL gate")
        self.sessions.add_decision(decision.run_id, decision)
        if decision.decision == HumanDecisionType.APPROVE:
            qa_hash = self._recorded_supervisor_hash(decision.run_id)
            if qa_hash is None:
                raise RuntimeCoordinatorError(
                    "Finalization requires recorded supervisor evidence"
                )
            result = final_result or FinalResult(
                run_id=decision.run_id,
                status="approved",
                summary=decision.feedback or "Final result approved by human.",
                supervisor_evidence_hash=qa_hash,
            )
            result.validate()
            if result.run_id != decision.run_id:
                raise RuntimeCoordinatorError(
                    "FinalResult.run_id must match the decision run_id"
                )
            if result.supervisor_evidence_hash != qa_hash:
                raise RuntimeCoordinatorError(
                    "FinalResult is not bound to the recorded supervisor evidence"
                )
            self.sessions.set_final_result(decision.run_id, result)
            self.sessions.transition(decision.run_id, WorkflowState.COMPLETED)
        elif decision.decision == HumanDecisionType.MODIFY:
            self.revisions.request_revision(
                decision.run_id,
                reason="Final result modification requested",
                source="human",
                feedback=decision.feedback,
            )
        elif decision.decision == HumanDecisionType.REJECT:
            self.sessions.transition(decision.run_id, WorkflowState.REJECTED)
        else:
            raise RuntimeCoordinatorError("Invalid final decision")
        return self.sessions.get_context(decision.run_id).state

    def record_revision(
        self,
        run_id,
        *,
        reason,
        source="runtime",
        feedback="",
    ):
        return self.revisions.request_revision(
            run_id,
            reason=reason,
            source=source,
            feedback=feedback,
        )

    def list_revisions(self, run_id):
        return self.revisions.list_revisions(run_id)

    def inspect_recovery(self, run_id):
        try:
            return self.recovery_resume.inspect(run_id)
        except RecoveryResumeError as exc:
            raise RuntimeCoordinatorError(str(exc)) from exc

    def resume_recovery(self, *, run_id, action, idempotency_key=None):
        try:
            result = self.recovery_resume.resume(
                run_id=run_id,
                action=action,
                idempotency_key=idempotency_key,
            )
        except RecoveryResumeError as exc:
            raise RuntimeCoordinatorError(str(exc)) from exc
        if result.resulting_state == WorkflowState.SUPERVISING and action in {
            RecoveryAction.RESUME_SUPERVISION,
            RecoveryAction.RECONCILE_EXECUTION,
        }:
            qa = self._supervise_recovered_run(run_id)
            if qa is not None:
                if qa.status == QAStatus.PASS:
                    self.record_supervisor_result(qa)
                    result = replace(
                        result,
                        resulting_state=WorkflowState.WAITING_FINAL_APPROVAL,
                    )
                elif qa.status == QAStatus.REVISE:
                    self.record_revision(
                        run_id,
                        reason="Recovered run failed supervisor QA",
                        source="supervisor",
                        feedback=qa.summary,
                    )
                    result = replace(
                        result,
                        resulting_state=self.sessions.get_context(run_id).state,
                    )
                else:
                    self.sessions.transition(run_id, WorkflowState.FAILED)
                    result = replace(
                        result,
                        resulting_state=WorkflowState.FAILED,
                    )
        return result

    def _supervise_recovered_run(self, run_id):
        snapshot = self.sessions.snapshot(run_id)
        plan = snapshot.architecture_plan
        if plan is None:
            self.sessions.add_message(
                run_id,
                role="system",
                content=(
                    "Recovered execution reached SUPERVISING but cannot be "
                    "QA-validated until its ArchitecturePlan is available."
                ),
                metadata={
                    "phase": "recovery",
                    "status": "blocked_missing_architecture_plan",
                },
            )
            return None
        return self.supervisor.evaluate(
            SupervisorInput(
                run_id=run_id,
                objective=plan.objective,
                acceptance_criteria=plan.acceptance_criteria,
                worker_outputs=tuple(snapshot.worker_outputs.values()),
                execution_results=snapshot.execution_results,
                artifacts=tuple(to_dict(artifact) for artifact in snapshot.artifacts),
            )
        )

    def _recorded_supervisor_hash(self, run_id: str) -> str | None:
        snapshot = self.sessions.snapshot(run_id)
        for message in reversed(snapshot.messages):
            if message.metadata.get("phase") != "qa":
                continue
            evidence_hash = message.metadata.get("evidence_hash")
            qa = message.metadata.get("qa_result")
            if isinstance(evidence_hash, str) and isinstance(qa, dict):
                if qa.get("run_id") != run_id or qa.get("status") != QAStatus.PASS.value:
                    continue
                if evidence_hash != _qa_hash_payload(qa):
                    raise RuntimeCoordinatorError(
                        "Persisted supervisor evidence hash does not match its QA payload"
                    )
                return evidence_hash
        return None

    def _validate_recorded_decision(self, decision: HumanDecision) -> None:
        decision.validate()
        gate = self.approvals.get_gate(decision.gate_id)
        if (
            gate.run_id != decision.run_id
            or gate.status != GateStatus.RESOLVED
        ):
            raise RuntimeCoordinatorError(
                "Decision gate is not a resolved gate for this run"
            )
        if self.approvals.get_decision(decision.gate_id) != decision:
            raise RuntimeCoordinatorError(
                "Decision is not the recorded result of its approval gate"
            )


def _qa_hash(result: QAResult) -> str:
    return _qa_hash_payload(to_dict(result))


def _qa_hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _latest_qa_message(messages) -> str | None:
    for message in reversed(messages):
        if message.metadata.get("phase") == "qa":
            value = message.metadata.get("evidence_hash")
            return value if isinstance(value, str) else None
    return None
