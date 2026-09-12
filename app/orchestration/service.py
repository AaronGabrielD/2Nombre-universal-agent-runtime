"""Integrated run orchestration across the runtime's bounded modules."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.approval.models import GateStatus
from app.core.config import Settings, get_settings
from app.core.contracts import ExecutionResult, HumanDecisionType, to_dict
from app.core.states import WorkflowState
from app.execution.models import ExecutionAuthorization, compute_authorization_proof
from app.runtime.service import RuntimeCoordinator
from app.session.manager import SessionManager
from app.session.models import WorkerOutput
from app.supervisor.models import QAResult, QAStatus, SupervisorInput
from app.supervisor.service import SupervisorService
from app.tools.authorization import ToolAuthorizationRequest, ToolAuthorizationService
from app.workers.models import DispatchBatch, WorkerInstance
from app.workers.runtime import WorkerRuntimeAdapter
from app.workers.service import WorkerDispatcher, WorkerFactory


class IntegratedOrchestrationError(RuntimeError):
    """Raised when the integrated execution path cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    run_id: str
    batches: tuple[DispatchBatch, ...]
    execution_results: tuple[ExecutionResult, ...]
    qa_result: QAResult | None
    final_gate_id: str | None = None
    pending_gate_id: str | None = None
    pending_worker_id: str | None = None


@dataclass(frozen=True, slots=True)
class _PendingToolGate:
    worker: WorkerInstance
    gate_id: str
    resolved_tool_ids: tuple[str, ...]


class IntegratedOrchestrator:
    """Execute the post-Gate-A lifecycle without bypassing runtime boundaries."""

    def __init__(
        self,
        *,
        coordinator: RuntimeCoordinator,
        session_manager: SessionManager | None = None,
        worker_factory: WorkerFactory | None = None,
        worker_dispatcher: WorkerDispatcher | None = None,
        worker_runtime: WorkerRuntimeAdapter | None = None,
        worker_agent=None,
        supervisor: SupervisorService | None = None,
        tool_authorization: ToolAuthorizationService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.sessions = session_manager or coordinator.sessions
        self.worker_factory = worker_factory or WorkerFactory()
        self.worker_dispatcher = worker_dispatcher or WorkerDispatcher()
        self.worker_agent = worker_agent
        self.worker_runtime = worker_runtime
        self.supervisor = supervisor or SupervisorService()
        self.tool_authorization = tool_authorization
        self.settings = settings or getattr(worker_runtime, "settings", None) or get_settings()

    def _grant_from_gate_a(
        self,
        run_id: str,
        gate_id: str,
        worker_id: str,
    ) -> ExecutionAuthorization:
        grant = ExecutionAuthorization(
            authorized=True,
            reason="worker execution authorized by Gate A",
            gate_id=gate_id,
            run_id=run_id,
            worker_id=worker_id,
            backend_id=self.settings.execution_backend,
            network_allowed=False,
        )
        if self.settings.execution_backend != "test":
            grant = ExecutionAuthorization(
                authorized=grant.authorized,
                reason=grant.reason,
                gate_id=grant.gate_id,
                run_id=grant.run_id,
                worker_id=grant.worker_id,
                backend_id=grant.backend_id,
                network_allowed=grant.network_allowed,
                proof=compute_authorization_proof(
                    self.settings.require_execution_authorization_secret(), grant
                ),
            )
        grant.validate()
        return grant

    def execute_run(self, run_id: str) -> OrchestrationResult:
        context = self.sessions.get_context(run_id)
        if context.state != WorkflowState.EXECUTING:
            raise IntegratedOrchestrationError(
                f"run {run_id} must be in EXECUTING, got {context.state.value}"
            )
        if self.worker_runtime is None:
            raise IntegratedOrchestrationError("WorkerRuntimeAdapter has not been configured")
        snapshot = self.sessions.snapshot(run_id)
        plan = snapshot.architecture_plan
        if plan is None:
            raise IntegratedOrchestrationError("run has no ArchitecturePlan")
        plan.validate()
        if self.worker_agent is None:
            raise IntegratedOrchestrationError("worker agent has not been configured")

        workers = self.worker_factory.create_workers(run_id=run_id, plan=plan)
        tasks = tuple(
            self.worker_dispatcher.build_task(
                worker_id=worker.worker_id,
                description=worker.mission,
                expected_output=", ".join(worker.deliverables) or "a completed worker result",
                required_tools=worker.required_tools,
            )
            for worker in workers
        )
        batches = self.worker_dispatcher.plan_batches(
            run_id=run_id,
            workers=workers,
            tasks=tasks,
        )
        gate_a = self._find_gate_a(run_id)
        all_results: list[ExecutionResult] = []

        for batch in batches:
            task_by_worker = {task.worker_id: task for task in batch.tasks}
            executable: list[tuple[WorkerInstance, Any, ExecutionAuthorization]] = []
            pending: list[_PendingToolGate] = []

            for worker in batch.workers:
                existing = self.sessions.snapshot(run_id).worker_outputs.get(worker.worker_id)
                if existing is not None and existing.status == "success":
                    continue
                task = task_by_worker.get(worker.worker_id)
                if task is None:
                    self._set_worker_error(
                        run_id,
                        worker,
                        "dispatcher produced no task for worker",
                    )
                    continue

                decision = self._authorize_worker_tools(
                    run_id=run_id,
                    worker=worker,
                    required_capabilities=tuple(
                        getattr(plan, "required_capabilities", ()) or ()
                    ),
                )
                if decision.gate_id is not None and decision.authorization is None:
                    self._mark_waiting_for_gate(run_id, worker, decision.gate_id)
                    pending.append(
                        _PendingToolGate(
                            worker,
                            decision.gate_id,
                            tuple(tool.tool_id for tool in decision.resolved_tools),
                        )
                    )
                    continue

                authorization = decision.authorization or self._grant_from_gate_a(
                    run_id,
                    gate_a,
                    worker.worker_id,
                )
                try:
                    execution_plan = self.worker_agent.build_execution_plan(
                        worker=worker,
                        task=task,
                        context={
                            "run_id": run_id,
                            "objective": plan.objective,
                            "acceptance_criteria": list(plan.acceptance_criteria),
                            "authorized_tools": [
                                tool.tool_id for tool in decision.resolved_tools
                            ],
                        },
                    )
                    if execution_plan.execution_task.needs_network and not authorization.network_allowed:
                        network_decision = self._authorize_network(
                            run_id=run_id,
                            worker=worker,
                            plan=plan,
                        )
                        if (
                            network_decision.gate_id is not None
                            and network_decision.authorization is None
                        ):
                            self._mark_waiting_for_gate(
                                run_id,
                                worker,
                                network_decision.gate_id,
                            )
                            pending.append(
                                _PendingToolGate(
                                    worker,
                                    network_decision.gate_id,
                                    tuple(
                                        tool.tool_id
                                        for tool in network_decision.resolved_tools
                                    ),
                                )
                            )
                            continue
                        authorization = (
                            network_decision.authorization or authorization
                        )
                    executable.append((worker, execution_plan, authorization))
                except (RuntimeError, ValueError) as exc:
                    self._set_worker_error(
                        run_id,
                        worker,
                        f"{type(exc).__name__}: {exc}",
                    )

            if executable:
                execution_workers = tuple(item[0] for item in executable)
                execution_tasks = tuple(item[1].execution_task.task for item in executable)
                execution_items = tuple(item[1].execution_task for item in executable)
                authorization_by_worker = {
                    worker.worker_id: authorization
                    for worker, _, authorization in executable
                }
                results = self.worker_runtime.execute_batch(
                    batch=DispatchBatch(
                        run_id=batch.run_id,
                        workers=execution_workers,
                        tasks=execution_tasks,
                        sequence=batch.sequence,
                    ),
                    tasks=execution_items,
                    authorization_by_worker=authorization_by_worker,
                    parallel=True,
                )
                all_results.extend(results)
                for (worker, execution_plan, _), result in zip(executable, results):
                    self.sessions.set_worker_output(
                        run_id,
                        WorkerOutput(
                            worker_id=worker.worker_id,
                            run_id=run_id,
                            status=(
                                "success"
                                if result.status.value == "success"
                                else result.status.value
                            ),
                            output={
                                "summary": execution_plan.summary,
                                "authorized_tools": list(worker.required_tools),
                                "execution": to_dict(result),
                            },
                        ),
                    )

            if pending:
                selected = pending[0]
                self.sessions.add_message(
                    run_id,
                    role="system",
                    content=(
                        f"Worker {selected.worker.worker_id} is paused pending "
                        "human Gate C approval."
                    ),
                    metadata={
                        "phase": "tool_authorization",
                        "gate_id": selected.gate_id,
                        "worker_id": selected.worker.worker_id,
                    },
                )
                self.sessions.transition(run_id, WorkflowState.WORKER_WAITING_HUMAN)
                return OrchestrationResult(
                    run_id=run_id,
                    batches=batches,
                    execution_results=tuple(all_results),
                    qa_result=None,
                    pending_gate_id=selected.gate_id,
                    pending_worker_id=selected.worker.worker_id,
                )

        self.sessions.transition(run_id, WorkflowState.SUPERVISING)
        final_snapshot = self.sessions.snapshot(run_id)
        qa = self.supervisor.evaluate(
            SupervisorInput(
                run_id=run_id,
                objective=plan.objective,
                acceptance_criteria=plan.acceptance_criteria,
                worker_outputs=tuple(final_snapshot.worker_outputs.values()),
                execution_results=final_snapshot.execution_results,
                artifacts=tuple(to_dict(item) for item in final_snapshot.artifacts),
            )
        )
        self.sessions.add_message(
            run_id,
            role="supervisor",
            content=qa.summary,
            metadata={"phase": "qa", "qa_result": to_dict(qa)},
        )
        final_gate_id = None
        if qa.status == QAStatus.PASS:
            final_gate_id = self.coordinator.record_supervisor_result(qa)
        elif qa.status == QAStatus.REVISE:
            self.coordinator.record_revision(
                run_id,
                reason="Supervisor requested a revision",
                source="supervisor",
                feedback=qa.summary,
            )
        else:
            self.sessions.transition(run_id, WorkflowState.FAILED)
        return OrchestrationResult(
            run_id=run_id,
            batches=batches,
            execution_results=tuple(all_results),
            qa_result=qa,
            final_gate_id=final_gate_id,
        )

    def resume_after_tool_gate(
        self,
        *,
        run_id: str,
        gate_id: str,
        decision: HumanDecisionType,
        worker_id: str,
        feedback: str,
        actor: str = "human",
    ) -> OrchestrationResult:
        context = self.sessions.get_context(run_id)
        if context.state != WorkflowState.WORKER_WAITING_HUMAN:
            raise IntegratedOrchestrationError(
                "tool-gate resume requires WORKER_WAITING_HUMAN"
            )
        if self.tool_authorization is None:
            raise IntegratedOrchestrationError(
                "ToolAuthorizationService is not configured"
            )

        gate = self.coordinator.approvals.get_gate(gate_id)
        needs_network = bool(gate.context.get("needs_network", False))
        authorization = self.tool_authorization.resolve_gate(
            gate_id=gate_id,
            decision=decision,
            run_id=run_id,
            worker_id=worker_id,
            feedback=feedback,
            actor=actor,
            backend_id=self.settings.execution_backend,
            needs_network=needs_network,
        )
        self.sessions.set_worker_output(
            run_id,
            WorkerOutput(
                worker_id=worker_id,
                run_id=run_id,
                status="approved" if authorization.authorized else "denied",
                output={
                    "gate_id": gate_id,
                    "decision": decision.value,
                    "feedback": feedback,
                },
            ),
        )
        if not authorization.authorized:
            self.coordinator.record_revision(
                run_id,
                reason="Risky tool authorization was denied",
                source=actor,
                feedback=feedback,
            )
            return OrchestrationResult(run_id, (), (), None)
        self.sessions.transition(run_id, WorkflowState.EXECUTING)
        return self.execute_run(run_id)

    def _authorize_worker_tools(
        self,
        *,
        run_id: str,
        worker: WorkerInstance,
        required_capabilities: tuple[str, ...],
    ):
        if not worker.required_tools and not required_capabilities:
            class _NoTools:
                resolved_tools = ()
                gate_id = None
                authorization = None
            return _NoTools()
        if self.tool_authorization is None:
            raise IntegratedOrchestrationError(
                "worker requires tool authorization, but no ToolAuthorizationService is configured"
            )
        return self.tool_authorization.request_authorization(
            ToolAuthorizationRequest(
                run_id=run_id,
                worker_id=worker.worker_id,
                required_tools=worker.required_tools,
                required_capabilities=required_capabilities,
                backend_id=self.settings.execution_backend,
            )
        )

    def _authorize_network(self, *, run_id: str, worker: WorkerInstance, plan):
        if self.tool_authorization is None:
            raise IntegratedOrchestrationError(
                "network execution requires ToolAuthorizationService"
            )
        return self.tool_authorization.request_authorization(
            ToolAuthorizationRequest(
                run_id=run_id,
                worker_id=worker.worker_id,
                required_tools=worker.required_tools,
                required_capabilities=tuple(getattr(plan, "required_capabilities", ()) or ()),
                backend_id=self.settings.execution_backend,
                needs_network=True,
            )
        )

    def _mark_waiting_for_gate(self, run_id: str, worker: WorkerInstance, gate_id: str) -> None:
        self.sessions.set_worker_output(
            run_id,
            WorkerOutput(
                worker_id=worker.worker_id,
                run_id=run_id,
                status="waiting_human",
                output={"gate": "TOOL_RISK", "gate_id": gate_id},
            ),
        )

    def _set_worker_error(self, run_id: str, worker: WorkerInstance, error: str) -> None:
        self.sessions.set_worker_output(
            run_id,
            WorkerOutput(
                worker_id=worker.worker_id,
                run_id=run_id,
                status="error",
                output={"error": error},
            ),
        )

    def _find_gate_a(self, run_id: str) -> str:
        for decision in reversed(self.sessions.snapshot(run_id).decisions):
            if decision.decision != HumanDecisionType.APPROVE:
                continue
            gate = self.coordinator.approvals.get_gate(decision.gate_id)
            if (
                gate.run_id == run_id
                and gate.kind == "ARCHITECTURE"
                and gate.status == GateStatus.RESOLVED
            ):
                return gate.gate_id
        raise IntegratedOrchestrationError(
            "no recorded human Gate-A approval is available for execution"
        )

    def _execution_authorization(self, run_id: str, worker_id: str) -> ExecutionAuthorization:
        return self._grant_from_gate_a(run_id, self._find_gate_a(run_id), worker_id)
