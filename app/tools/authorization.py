"""Tool authorization boundary for M07/M05/M08 integration."""
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
    backend_id: str = "docker"
    needs_network: bool = False

    def validate(self) -> None:
        for name, value in (("run_id", self.run_id), ("worker_id", self.worker_id), ("backend_id", self.backend_id)):
            if not isinstance(value, str) or not value.strip():
                raise ToolAuthorizationError(f"{name} cannot be empty")
        if not isinstance(self.needs_network, bool):
            raise ToolAuthorizationError("needs_network must be boolean")


@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    run_id: str
    worker_id: str
    validation: RegistryValidation
    resolved_tools: tuple[ToolRegistration, ...]
    gate_id: str | None = None
    authorization: ExecutionAuthorization | None = None


class ToolAuthorizationService:
    """Resolve tool requirements and gate risky or network-enabled access."""

    def __init__(self, *, registry: ToolRegistry, approvals: HumanApprovalEngine) -> None:
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
                f"tool requirements unavailable: tools={validation.missing_tools}, capabilities={validation.missing_capabilities}"
            )

        resolved = validation.resolved_tools
        risky = tuple(tool for tool in resolved if tool.risk_level == RiskLevel.HIGH or tool.requires_human_approval)
        sensitive = bool(risky or request.needs_network)
        if not sensitive:
            return ToolAuthorizationDecision(
                run_id=request.run_id, worker_id=request.worker_id, validation=validation,
                resolved_tools=resolved,
                authorization=ExecutionAuthorization(
                    authorized=True, reason="resolved tools require no human approval",
                    run_id=request.run_id, worker_id=request.worker_id,
                    backend_id=request.backend_id, network_allowed=False,
                ),
            )

        required_tool_ids = tuple(sorted(tool.tool_id for tool in risky))
        required_capabilities = tuple(sorted(request.required_capabilities))
        matching = self._find_matching_gate(request, required_tool_ids, required_capabilities)
        if matching is not None and matching.status == GateStatus.RESOLVED:
            recorded = self.approvals.get_decision(matching.gate_id)
            if recorded is None:
                raise ToolAuthorizationError(f"resolved Gate C {matching.gate_id} has no recorded decision")
            approved = recorded.decision == HumanDecisionType.APPROVE
            return ToolAuthorizationDecision(
                run_id=request.run_id, worker_id=request.worker_id, validation=validation,
                resolved_tools=resolved, gate_id=matching.gate_id,
                authorization=ExecutionAuthorization(
                    authorized=approved,
                    reason="human approved execution" if approved else "human rejected execution",
                    gate_id=matching.gate_id, run_id=request.run_id, worker_id=request.worker_id,
                    backend_id=request.backend_id, network_allowed=request.needs_network and approved,
                ),
            )
        if matching is not None and matching.status == GateStatus.OPEN:
            return ToolAuthorizationDecision(run_id=request.run_id, worker_id=request.worker_id,
                validation=validation, resolved_tools=resolved, gate_id=matching.gate_id)

        gate = self.approvals.request_gate(
            run_id=request.run_id, kind="TOOL_RISK", title="Approve sensitive tool execution",
            prompt="A requested tool or network access requires human approval before execution.",
            context={"worker_id": request.worker_id, "tools": list(required_tool_ids),
                     "required_tools": list(request.required_tools),
                     "required_capabilities": list(request.required_capabilities),
                     "backend_id": request.backend_id, "needs_network": request.needs_network},
            allowed_decisions=(HumanDecisionType.APPROVE, HumanDecisionType.REJECT),
        )
        return ToolAuthorizationDecision(run_id=request.run_id, worker_id=request.worker_id,
            validation=validation, resolved_tools=resolved, gate_id=gate.gate_id)

    def resolve_gate(self, *, gate_id: str, decision: HumanDecisionType, run_id: str,
                     worker_id: str, feedback: str, actor: str = "human",
                     backend_id: str = "docker", needs_network: bool = False) -> ExecutionAuthorization:
        gate = self.approvals.get_gate(gate_id)
        if gate.run_id != run_id or gate.kind != "TOOL_RISK":
            raise ToolAuthorizationError("gate does not belong to this tool authorization request")
        if gate.context.get("worker_id") != worker_id:
            raise ToolAuthorizationError("gate does not belong to this worker")
        if gate.context.get("backend_id", backend_id) != backend_id or bool(gate.context.get("needs_network", needs_network)) != needs_network:
            raise ToolAuthorizationError("execution scope does not match the approved gate")
        recorded = self.approvals.resolve_gate(gate_id=gate_id, decision=decision, feedback=feedback, actor=actor)
        approved = recorded.decision == HumanDecisionType.APPROVE
        return ExecutionAuthorization(authorized=approved,
            reason="human approved execution" if approved else "human rejected execution",
            gate_id=gate_id, run_id=run_id, worker_id=worker_id, backend_id=backend_id,
            network_allowed=needs_network and approved)

    def _find_matching_gate(self, request: ToolAuthorizationRequest, required_tool_ids: tuple[str, ...], required_capabilities: tuple[str, ...]):
        for gate in reversed(self.approvals.list_gates(run_id=request.run_id, kind="TOOL_RISK")):
            context = gate.context
            if context.get("worker_id") != request.worker_id:
                continue
            if tuple(sorted(context.get("tools", ()))) != required_tool_ids:
                continue
            if tuple(sorted(context.get("required_capabilities", ()))) != required_capabilities:
                continue
            if context.get("backend_id", request.backend_id) != request.backend_id:
                continue
            if bool(context.get("needs_network", False)) != request.needs_network:
                continue
            return gate
        return None
