"""Integrated run orchestration across the runtime's bounded modules."""
from __future__ import annotations
from dataclasses import dataclass
from app.agents.crewai_adapter import CrewAIWorkerAdapter
from app.approval.models import GateStatus
from app.core.config import get_settings
from app.core.contracts import ExecutionResult, HumanDecisionType, to_dict
from app.core.states import WorkflowState
from app.execution.models import ExecutionAuthorization
from app.session.manager import SessionManager
from app.session.models import WorkerOutput
from app.supervisor.models import QAResult, QAStatus, SupervisorInput
from app.supervisor.service import SupervisorService
from app.tools.authorization import ToolAuthorizationRequest,ToolAuthorizationService
from app.workers.models import DispatchBatch,WorkerInstance
from app.workers.runtime import WorkerRuntimeAdapter,WorkerRuntimeError
from app.workers.service import WorkerDispatcher,WorkerFactory
from app.runtime.service import RuntimeCoordinator
class IntegratedOrchestrationError(RuntimeError):pass
@dataclass(frozen=True,slots=True)
class OrchestrationResult:
    run_id:str;batches:tuple[DispatchBatch,...];execution_results:tuple[ExecutionResult,...];qa_result:QAResult|None;final_gate_id:str|None=None;pending_gate_id:str|None=None;pending_worker_id:str|None=None
@dataclass(frozen=True,slots=True)
class _PendingToolGate:worker:WorkerInstance;gate_id:str;resolved_tool_ids:tuple[str,...]
class IntegratedOrchestrator:
    def __init__(self,*,coordinator,session_manager=None,worker_factory=None,worker_dispatcher=None,worker_runtime=None,worker_agent=None,supervisor=None,tool_authorization=None):
        self.coordinator=coordinator;self.sessions=session_manager or coordinator.sessions;self.worker_factory=worker_factory or WorkerFactory();self.worker_dispatcher=worker_dispatcher or WorkerDispatcher();self.worker_agent=worker_agent or CrewAIWorkerAdapter();self.worker_runtime=worker_runtime;self.supervisor=supervisor or SupervisorService();self.tool_authorization=tool_authorization;self.settings=getattr(worker_runtime,"settings",None) or get_settings()
    def execute_run(self,run_id):
        if self.sessions.get_context(run_id).state!=WorkflowState.EXECUTING:raise IntegratedOrchestrationError("run must be in EXECUTING")
        if self.worker_runtime is None:raise IntegratedOrchestrationError("WorkerRuntimeAdapter has not been configured")
        snap=self.sessions.snapshot(run_id);plan=snap.architecture_plan
        if plan is None:raise IntegratedOrchestrationError("run has no ArchitecturePlan")
        plan.validate();workers=self.worker_factory.create_workers(run_id=run_id,plan=plan);tasks=tuple(self.worker_dispatcher.build_task(worker_id=w.worker_id,description=w.mission,expected_output=", ".join(w.deliverables) or "a completed worker result",required_tools=w.required_tools) for w in workers);batches=self.worker_dispatcher.plan_batches(run_id=run_id,workers=workers,tasks=tasks);gate_a=self._execution_authorization(run_id);all_results=[]
        for batch in batches:
            by_worker={t.worker_id:t for t in batch.tasks};executable=[];pending=[]
            for worker in batch.workers:
                existing=self.sessions.snapshot(run_id).worker_outputs.get(worker.worker_id)
                if existing is not None and existing.status=="success":continue
                task=by_worker.get(worker.worker_id)
                if task is None:self._set_worker_error(run_id,worker,"dispatcher produced no task for worker");continue
                td=self._authorize_worker_tools(run_id=run_id,worker=worker,required_capabilities=tuple(getattr(plan,"required_capabilities",()) or ()))
                if td.gate_id is not None and td.authorization is None:
                    self.sessions.set_worker_output(run_id,WorkerOutput(worker.worker_id,run_id,"waiting_human",{"gate":"TOOL_RISK","gate_id":td.gate_id}));pending.append(_PendingToolGate(worker,td.gate_id,tuple(t.tool_id for t in td.resolved_tools)));continue
                auth=td.authorization or gate_a
                try:
                    ep=self.worker_agent.build_execution_plan(worker=worker,task=task,context={"run_id":run_id,"objective":plan.objective,"acceptance_criteria":list(plan.acceptance_criteria),"authorized_tools":[t.tool_id for t in td.resolved_tools]})
                    if ep.execution_task.needs_network and not auth.network_allowed:
                        if self.tool_authorization is None:raise IntegratedOrchestrationError("network execution requires ToolAuthorizationService")
                        nd=self.tool_authorization.request_authorization(ToolAuthorizationRequest(run_id=run_id,worker_id=worker.worker_id,required_tools=worker.required_tools,required_capabilities=tuple(getattr(plan,"required_capabilities",()) or ()),backend_id=self.settings.execution_backend,needs_network=True))
                        if nd.gate_id is not None and nd.authorization is None:pending.append(_PendingToolGate(worker,nd.gate_id,tuple(t.tool_id for t in nd.resolved_tools)));continue
                        auth=nd.authorization or auth
                    executable.append((worker,ep,auth))
                except (RuntimeError,ValueError) as exc:self._set_worker_error(run_id,worker,f"{type(exc).__name__}: {exc}")
            if executable:
                results=[]
                # A grant scoped to one worker must never be reused for another worker.
                # Group only identical grants; otherwise cross-worker execution is serialized.
                groups=[]
                for item in executable:
                    for group in groups:
                        if group[0][2]==item[2]:group.append(item);break
                    else:groups.append([item])
                try:
                    for group in groups:
                        for worker,ep,auth in group:
                            results.extend(self.worker_runtime.execute_batch(batch=DispatchBatch(batch.run_id,(worker,),(ep.execution_task.task,),batch.sequence),tasks=(ep.execution_task,),authorization=auth,parallel=False))
                except (WorkerRuntimeError,RuntimeError,ValueError) as exc:
                    for worker,_,_ in executable:self._set_worker_error(run_id,worker,f"{type(exc).__name__}: {exc}")
                    results=[]
                all_results.extend(results)
                for (worker,ep,_),result in zip(executable,results):self.sessions.set_worker_output(run_id,WorkerOutput(worker.worker_id,run_id,"success" if result.status.value=="success" else result.status.value,{"summary":ep.summary,"authorized_tools":list(worker.required_tools),"execution":to_dict(result)}))
            if pending:
                p=pending[0];self.sessions.add_message(run_id,role="system",content=f"Worker {p.worker.worker_id} is paused pending human Gate C approval.",metadata={"phase":"tool_authorization","gate_id":p.gate_id,"worker_id":p.worker.worker_id});self.sessions.transition(run_id,WorkflowState.WORKER_WAITING_HUMAN);return OrchestrationResult(run_id,batches,tuple(all_results),None,pending_gate_id=p.gate_id,pending_worker_id=p.worker.worker_id)
        self.sessions.transition(run_id,WorkflowState.SUPERVISING);s=self.sessions.snapshot(run_id);qa=self.supervisor.evaluate(SupervisorInput(run_id=run_id,objective=plan.objective,acceptance_criteria=plan.acceptance_criteria,worker_outputs=tuple(s.worker_outputs.values()),execution_results=s.execution_results,artifacts=tuple(to_dict(a) for a in s.artifacts)));self.sessions.add_message(run_id,role="supervisor",content=qa.summary,metadata={"phase":"qa","qa_result":to_dict(qa)});gate=None
        if qa.status==QAStatus.PASS:gate=self.coordinator.record_supervisor_result(qa)
        elif qa.status==QAStatus.REVISE:self.coordinator.record_revision(run_id,reason="Supervisor requested a revision",source="supervisor",feedback=qa.summary)
        else:self.sessions.transition(run_id,WorkflowState.FAILED)
        return OrchestrationResult(run_id,batches,tuple(all_results),qa,final_gate_id=gate)
    def resume_after_tool_gate(self,*,run_id,gate_id,decision,worker_id,feedback,actor="human"):
        if self.sessions.get_context(run_id).state!=WorkflowState.WORKER_WAITING_HUMAN:raise IntegratedOrchestrationError("tool-gate resume requires WORKER_WAITING_HUMAN")
        if self.tool_authorization is None:raise IntegratedOrchestrationError("ToolAuthorizationService is not configured")
        auth=self.tool_authorization.resolve_gate(gate_id=gate_id,decision=decision,run_id=run_id,worker_id=worker_id,feedback=feedback,actor=actor,backend_id=self.settings.execution_backend,needs_network=True);self.sessions.set_worker_output(run_id,WorkerOutput(worker_id,run_id,"approved" if auth.authorized else "denied",{"gate_id":gate_id,"decision":decision.value,"feedback":feedback}))
        if not auth.authorized:self.coordinator.record_revision(run_id,reason="Risky tool authorization was denied",source=actor,feedback=feedback);return OrchestrationResult(run_id,(),(),None)
        self.sessions.transition(run_id,WorkflowState.EXECUTING);return self.execute_run(run_id)
    def _authorize_worker_tools(self,*,run_id,worker,required_capabilities):
        if not worker.required_tools and not required_capabilities:
            class _NoTools:resolved_tools=();gate_id=None;authorization=None
            return _NoTools()
        if self.tool_authorization is None:raise IntegratedOrchestrationError("worker requires tool authorization, but no ToolAuthorizationService is configured")
        return self.tool_authorization.request_authorization(ToolAuthorizationRequest(run_id=run_id,worker_id=worker.worker_id,required_tools=worker.required_tools,required_capabilities=required_capabilities,backend_id=self.settings.execution_backend))
    def _set_worker_error(self,run_id,worker,error):self.sessions.set_worker_output(run_id,WorkerOutput(worker.worker_id,run_id,"error",{"error":error}))
    def _execution_authorization(self,run_id):
        for decision in reversed(self.sessions.snapshot(run_id).decisions):
            if decision.decision!=HumanDecisionType.APPROVE:continue
            gate=self.coordinator.approvals.get_gate(decision.gate_id)
            if gate.run_id==run_id and gate.kind=="ARCHITECTURE" and gate.status==GateStatus.RESOLVED:
                grant=ExecutionAuthorization(True,"worker execution authorized by Gate A",gate.gate_id,run_id,"*",self.settings.execution_backend,False);grant.validate();return grant
        raise IntegratedOrchestrationError("no recorded human Gate-A approval is available for execution")
