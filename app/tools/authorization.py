"""Tool authorization boundary for M07/M05/M08 integration.

This service resolves declarative tool requirements and turns risky tool use into
an explicit human Gate C decision. It never invokes tool handlers itself.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.approval.models import GateStatus
from app.approval.service import HumanApprovalEngine
from app.core.contracts import HumanDecisionType, RiskLevel
from app.execution.models import ExecutionAuthorization

from .models import RegistryValidation, ToolRegistration
from .service import ToolRegistry


class ToolAuthorizationError(RuntimeError):
    """Raised when tool access cannot be safely authorized."""


@dataclass(frozen=True, slots=True)
class ToolAuthorizationRequest:
    run_id: str
    worker_id: str
    required_tools: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.run_id.strip():
            raise ToolAuthorizationError("run_id cannot be empty")
        if not self.worker_id.strip():
            raise ToolAuthorizationError("worker_id cannot be empty")


@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    run_id: str
    worker_id: str
    validation: RegistryValidation
    resolved_tools: tuple[ToolRegistration, ...]
    gate_id: str | None = None
    authorization: ExecutionAuthorization | None = None


class ToolAuthorizationService:
    """Resolve tool requirements and gate risky access."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        approvals: HumanApprovalEngine,
    ) -> None:
        self.registry = registry
        self.approvals = approvals

    def request_authorization(self, request: ToolAuthorizationRequest) -> ToolAuthorizationDecision:
        request.validate()
        validation = self.registry.validate_requirements(
            required_tools=request.required_tools,
            required_capabilities=request.required_capabilities,
        )
        if not validation.is_valid:
            raise ToolAuthorizationError(
                f"tool requirements unavailable: tools={validation.missing_tools}, "
                f"capabilities={validation.missing_capabilities}"
            )

        resolved = validation.resolved_tools
        risky = tuple(
            tool for tool in resolved
            if tool.risk_level == RiskLevel.HIGH or tool.requires_human_approval
        )
        if not risky:
            return ToolAuthorizationDecision(
                run_id=request.run_id,
                worker_id=request.worker_id,
                validation=validation,
                resolved_tools=resolved,
                authorization=ExecutionAuthorization(
                    authorized=True,
                    reason="resolved tools require no human approval",
                ),
            )

        matching = self._find_matching_gate(request=request, risky=risky)
        if matching is not None:
            if matching.status == GateStatus.OPEN:
                return ToolAuthorizationDecision(
                    run_id=request.run_id,
                    worker_id=request.worker_id,
                    validation=validation,
                    resolved_tools=resolved,
                    gate_id=matching.gate_id,
                )
            if matching.status == GateStatus.RESOLVED:
                recorded = self.approvals.get_decision(matching.gate_id)
                if recorded is None:
                    raise ToolAuthorizationError(
                        f"resolved Gate C {matching.gate_id} has no recorded decision"
                    )
                approved = recorded.decision == HumanDecisionType.APPROVE
                return ToolAuthorizationDecision(
                    run_id=request.run_id,
                    worker_id=request.worker_id,
                    validation=validation,
                    resolved_tools=resolved,
                    gate_id=matching.gate_id,
                    authorization=ExecutionAuthorization(
                        authorized=approved,
                        reason=(
                            "human approved risky tool execution"
                            if approved
                            else "human rejected risky tool execution"
                        ),
                        gate_id=matching.gate_id,
                    ),
                )

        gate = self.approvals.request_gate(
            run_id=request.run_id,
            kind="TOOL_RISK",
            title="Approve risky tool execution",
            prompt="A requested tool requires human approval before it may execute.",
            context={
                "worker_id": request.worker_id,
                "tools": [tool.tool_id for tool in risky],
                "required_tools": list(request.required_tools),
                "required_capabilities": list(request.required_capabilities),
            },
            allowed_decisions=(HumanDecisionType.APPROVE, HumanDecisionType.REJECT),
        )
        return ToolAuthorizationDecision(
            run_id=request.run_id,
            worker_id=request.worker_id,
            validation=validation,
            resolved_tools=resolved,
            gate_id=gate.gate_id,
        )

    def resolve_gate(
        self,
        *,
        gate_id: str,
        decision: HumanDecisionType,
        run_id: str,
        worker_id: str,
        feedback: str,
        actor: str = "human",
    ) -> ExecutionAuthorization:
        gate = self.approvals.get_gate(gate_id)
        if gate.run_id != run_id or gate.kind != "TOOL_RISK":
            raise ToolAuthorizationError("gate does not belong to this tool authorization request")
        gated_worker = gate.context.get("worker_id")
        if gated_worker != worker_id:
            raise ToolAuthorizationError("gate does not belong to this worker")

        recorded = self.approvals.resolve_gate(
            gate_id=gate_id,
            decision=decision,
            feedback=feedback,
            actor=actor,
        )
        if recorded.run_id != run_id:
            raise ToolAuthorizationError("decision/run ownership mismatch")
        if decision != HumanDecisionType.APPROVE:
            return ExecutionAuthorization(
                authorized=False,
                reason="human rejected risky tool execution",
                gate_id=gate_id,
            )
        return ExecutionAuthorization(
            authorized=True,
            reason="human approved risky tool execution",
            gate_id=gate_id,
        )

    def _find_matching_gate(
        self,
        *,
        request: ToolAuthorizationRequest,
        risky: tuple[ToolRegistration, ...],
    ):
        required_tool_ids = tuple(sorted(tool.tool_id for tool in risky))
        required_capabilities = tuple(sorted(request.required_capabilities))
        for gate in reversed(self.approvals.list_gates(run_id=request.run_id, kind="TOOL_RISK")):
            context = gate.context
            if context.get("worker_id") != request.worker_id:
                continue
            if tuple(sorted(context.get("tools", ()))) != required_tool_ids:
                continue
            if tuple(sorted(context.get("required_capabilities", ()))) != required_capabilities:
                continue
            return gate
        return None
