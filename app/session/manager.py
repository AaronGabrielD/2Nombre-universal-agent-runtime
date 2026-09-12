"""Public M01 API for lifecycle and isolated session state."""
from __future__ import annotations
from copy import deepcopy
from threading import RLock
from typing import Any
from app.approval.models import ApprovalGate, GateStatus
from app.core.contracts import ArchitecturePlan, ArtifactRef, ExecutionResult, FinalResult, HumanDecision
from app.core.models import EventRecord, RunContext
from app.core.states import TERMINAL_STATES, WorkflowState
from .models import SessionMessage, SessionRecord, WorkerOutput
from .repository import InMemorySessionRepository, SessionRepository

class SessionManager:
    def __init__(self,repository:SessionRepository|None=None):self.repository=repository or InMemorySessionRepository();self._lock=RLock()
    def create_session(self,*,metadata:dict[str,str]|None=None):
        context=RunContext(metadata=dict(metadata or {}))
        with self._lock:self.repository.create(SessionRecord(context=context));return deepcopy(context)
    def destroy_session(self,run_id):
        with self._lock:self.repository.delete(run_id)
    def get_context(self,run_id):
        with self._lock:return deepcopy(self.repository.get(run_id).context)
    def list_sessions(self):
        with self._lock:return tuple(deepcopy(r) for r in self.repository.list())
    def list_recoverable_sessions(self):
        with self._lock:return tuple(deepcopy(r) for r in self.repository.list() if r.context.state not in TERMINAL_STATES)
    def transition(self,run_id,target):
        with self._lock:r=self.repository.get(run_id);r.context.transition_to(target);self.repository.save(r);return deepcopy(r.context)
    def add_message(self,run_id,*,role,content,metadata=None):
        if not isinstance(role,str) or not role.strip() or not isinstance(content,str) or not content.strip():raise ValueError("role/content cannot be empty")
        if metadata is not None and not isinstance(metadata,dict):raise ValueError("metadata must be a mapping")
        message=SessionMessage(run_id=run_id,role=role,content=content,metadata=deepcopy(metadata or {}))
        with self._lock:r=self.repository.get(run_id);r.messages.append(message);self.repository.save(r)
        return deepcopy(message)
    def add_artifact(self,run_id,artifact):
        artifact.validate()
        with self._lock:
            r=self.repository.get(run_id)
            if any(a.artifact_id==artifact.artifact_id for a in r.artifacts):raise ValueError(f"artifact already exists: {artifact.artifact_id}")
            r.artifacts.append(deepcopy(artifact));self.repository.save(r)
    def add_decision(self,run_id,decision):
        decision.validate()
        if decision.run_id!=run_id:raise ValueError("HumanDecision.run_id must match target session")
        with self._lock:
            r=self.repository.get(run_id)
            if any(d.gate_id==decision.gate_id for d in r.decisions):
                if any(d==decision for d in r.decisions):return
                raise ValueError(f"decision already exists for gate {decision.gate_id}")
            r.decisions.append(deepcopy(decision));self.repository.save(r)
    def add_execution_result(self,run_id,result):
        result.validate()
        if result.run_id is not None and result.run_id!=run_id:raise ValueError("ExecutionResult.run_id must match target session")
        if result.run_id is None:result=ExecutionResult(execution_id=result.execution_id,run_id=run_id,status=result.status,exit_code=result.exit_code,stdout=result.stdout,stderr=result.stderr,duration_ms=result.duration_ms,artifacts=result.artifacts,backend=result.backend)
        with self._lock:
            r=self.repository.get(run_id);existing=next((x for x in r.execution_results if x.execution_id==result.execution_id),None)
            if existing is not None:
                if existing!=result:raise ValueError(f"conflicting execution result: {result.execution_id}")
                return
            r.execution_results.append(deepcopy(result));self.repository.save(r)
    def add_approval_gate(self,run_id,gate):
        gate.validate()
        if gate.run_id!=run_id:raise ValueError("ApprovalGate.run_id must match target session")
        with self._lock:r=self.repository.get(run_id);r.approval_gates.append(deepcopy(gate));self.repository.save(r);return deepcopy(gate)
    def resolve_approval_gate(self,run_id,gate,decision):
        gate.validate();decision.validate()
        if gate.run_id!=run_id or decision.run_id!=run_id or decision.gate_id!=gate.gate_id or gate.status!=GateStatus.RESOLVED:raise ValueError("invalid resolved approval gate scope")
        with self._lock:
            r=self.repository.get(run_id);idx=next((i for i,g in enumerate(r.approval_gates) if g.gate_id==gate.gate_id),None)
            if idx is None or r.approval_gates[idx].status!=GateStatus.OPEN or any(d.gate_id==decision.gate_id for d in r.decisions):raise ValueError("gate cannot be resolved")
            r.approval_gates[idx]=deepcopy(gate);r.decisions.append(deepcopy(decision));self.repository.save(r)
        return deepcopy(gate)
    def cancel_approval_gate(self,run_id,gate):
        gate.validate()
        if gate.run_id!=run_id or gate.status!=GateStatus.CANCELLED:raise ValueError("invalid cancelled approval gate")
        with self._lock:r=self.repository.get(run_id);idx=next((i for i,g in enumerate(r.approval_gates) if g.gate_id==gate.gate_id),None)
        if idx is None:raise ValueError(f"unknown gate: {gate.gate_id}")
        if r.approval_gates[idx].status!=GateStatus.OPEN:raise ValueError("gate is not open")
        r.approval_gates[idx]=deepcopy(gate);self.repository.save(r);return deepcopy(gate)
    def set_architecture_plan(self,run_id,plan):
        plan.validate()
        with self._lock:r=self.repository.get(run_id);r.architecture_plan=deepcopy(plan);self.repository.save(r)
    def set_worker_output(self,run_id,output):
        if not isinstance(output.worker_id,str) or not output.worker_id.strip() or output.run_id!=run_id:raise ValueError("WorkerOutput identity must match target session")
        if not isinstance(output.status,str) or not output.status.strip():raise ValueError("WorkerOutput status must be non-empty")
        with self._lock:r=self.repository.get(run_id);r.worker_outputs[output.worker_id]=deepcopy(output);self.repository.save(r)
    def set_final_result(self,run_id,result):
        result.validate()
        if result.run_id!=run_id:raise ValueError("FinalResult.run_id must match target session")
        with self._lock:r=self.repository.get(run_id);r.final_result=deepcopy(result);self.repository.save(r)
    def snapshot(self,run_id):
        with self._lock:return deepcopy(self.repository.get(run_id))
    @staticmethod
    def event_for(run_id,*,event_type,message,status="info"):return EventRecord(run_id=run_id,component="session_manager",event_type=event_type,status=status,short_message=message)
