"""Tool authorization boundary for M07/M05/M08 integration."""
from __future__ import annotations
from dataclasses import dataclass
from app.approval.models import GateStatus
from app.approval.service import HumanApprovalEngine
from app.core.contracts import HumanDecisionType, RiskLevel
from app.execution.models import ExecutionAuthorization
from .models import RegistryValidation, ToolRegistration
from .service import ToolRegistry
class ToolAuthorizationError(RuntimeError): pass
@dataclass(frozen=True,slots=True)
class ToolAuthorizationRequest:
    run_id:str; worker_id:str; required_tools:tuple[str,...]=(); required_capabilities:tuple[str,...]=(); backend_id:str="docker"; needs_network:bool=False
    def validate(self):
        for n,v in (("run_id",self.run_id),("worker_id",self.worker_id),("backend_id",self.backend_id)):
            if not isinstance(v,str) or not v.strip():raise ToolAuthorizationError(f"{n} cannot be empty")
        if not isinstance(self.needs_network,bool):raise ToolAuthorizationError("needs_network must be boolean")
@dataclass(frozen=True,slots=True)
class ToolAuthorizationDecision:
    run_id:str; worker_id:str; validation:RegistryValidation; resolved_tools:tuple[ToolRegistration,...]; gate_id:str|None=None; authorization:ExecutionAuthorization|None=None
class ToolAuthorizationService:
    def __init__(self,*,registry:ToolRegistry,approvals:HumanApprovalEngine):self.registry=registry;self.approvals=approvals
    def request_authorization(self,request):
        request.validate();validation=self.registry.validate_requirements(required_tools=request.required_tools,required_capabilities=request.required_capabilities)
        if not validation.is_valid:raise ToolAuthorizationError(f"tool requirements unavailable: tools={validation.missing_tools}, capabilities={validation.missing_capabilities}")
        resolved=validation.resolved_tools;risky=tuple(t for t in resolved if t.risk_level==RiskLevel.HIGH or t.requires_human_approval)
        if not risky and not request.needs_network:return ToolAuthorizationDecision(request.run_id,request.worker_id,validation,resolved,authorization=ExecutionAuthorization(True,"resolved tools require no human approval",run_id=request.run_id,worker_id=request.worker_id,backend_id=request.backend_id))
        tool_ids=tuple(sorted(t.tool_id for t in risky));caps=tuple(sorted(request.required_capabilities));matching=self._find_matching_gate(request,tool_ids,caps)
        if matching is not None and matching.status==GateStatus.RESOLVED:
            recorded=self.approvals.get_decision(matching.gate_id)
            if recorded is None:raise ToolAuthorizationError("resolved Gate C has no recorded decision")
            approved=recorded.decision==HumanDecisionType.APPROVE;gate_network=bool(matching.context.get("needs_network",False))
            return ToolAuthorizationDecision(request.run_id,request.worker_id,validation,resolved,matching.gate_id,ExecutionAuthorization(approved,"human approved execution" if approved else "human rejected execution",matching.gate_id,request.run_id,request.worker_id,matching.context.get("backend_id",request.backend_id),gate_network and approved))
        if matching is not None:return ToolAuthorizationDecision(request.run_id,request.worker_id,validation,resolved,matching.gate_id)
        gate=self.approvals.request_gate(run_id=request.run_id,kind="TOOL_RISK",title="Approve sensitive tool execution",prompt="A requested tool or network access requires human approval before execution.",context={"worker_id":request.worker_id,"tools":list(tool_ids),"required_tools":list(request.required_tools),"required_capabilities":list(request.required_capabilities),"backend_id":request.backend_id,"needs_network":request.needs_network},allowed_decisions=(HumanDecisionType.APPROVE,HumanDecisionType.REJECT))
        return ToolAuthorizationDecision(request.run_id,request.worker_id,validation,resolved,gate.gate_id)
    def resolve_gate(self,*,gate_id,decision,run_id,worker_id,feedback,actor="human",backend_id="docker",needs_network=False):
        gate=self.approvals.get_gate(gate_id)
        if gate.run_id!=run_id or gate.kind!="TOOL_RISK" or gate.context.get("worker_id")!=worker_id:raise ToolAuthorizationError("gate does not belong to this authorization request")
        durable_backend=gate.context.get("backend_id");durable_network=bool(gate.context.get("needs_network",False))
        if durable_backend is not None and durable_backend!=backend_id:raise ToolAuthorizationError("execution backend does not match approved gate")
        # The durable gate is authoritative; callers cannot widen network scope while resuming.
        recorded=self.approvals.resolve_gate(gate_id=gate_id,decision=decision,feedback=feedback,actor=actor);approved=recorded.decision==HumanDecisionType.APPROVE
        return ExecutionAuthorization(approved,"human approved execution" if approved else "human rejected execution",gate_id,run_id,worker_id,durable_backend or backend_id,durable_network and approved)
    def _find_matching_gate(self,request,required_tool_ids,required_capabilities):
        for gate in reversed(self.approvals.list_gates(run_id=request.run_id,kind="TOOL_RISK")):
            c=gate.context
            if c.get("worker_id")!=request.worker_id or tuple(sorted(c.get("tools",())))!=required_tool_ids or tuple(sorted(c.get("required_capabilities",())))!=required_capabilities or c.get("backend_id",request.backend_id)!=request.backend_id or bool(c.get("needs_network",False))!=request.needs_network:continue
            return gate
        return None
