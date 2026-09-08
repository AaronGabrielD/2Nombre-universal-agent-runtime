"""Integrated run orchestration across the runtime's bounded modules.

M15 coordinates the worker lifecycle while preserving the runtime's own
approval, tool-authorization, execution, and QA boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.crewai_adapter import CrewAIWorkerAdapter
from app.approval.models import GateStatus
from app.core.contracts import ExecutionResult, HumanDecisionType, to_dict
from app.core.states import WorkflowState
from app.execution.models import ExecutionAuthorization
from app.session.manager import SessionManager
from app.session.models import WorkerOutput
from app.supervisor.models import QAResult, QAStatus, SupervisorInput
from app.supervisor.service import SupervisorService
from app.tools.authorization import ToolAuthorizationRequest, ToolAuthorizationService
from app.workers.models import DispatchBatch, WorkerInstance
from app.workers.runtime import WorkerExecutionTask, WorkerRuntimeAdapter, WorkerRuntimeError
from app.workers.service import WorkerDispatcher, WorkerFactory
from app.runtime.service import RuntimeCoordinator


class IntegratedOrchestrationError(RuntimeError):
    """Raised when the integrated execution path cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Evidence produced by one orchestration pass, optionally paused at Gate C."""

    run_id: str
    batches: tuple[DispatchBatch, ...]
    execution_results: tuple[ExecutionResult, ...]
    qa_result: QAResult | None
    final_gate_id: str | None = None
    pending_gate_id: str | None = None
    pending_worker_id: str | None = None


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
        worker_agent: CrewAIWorkerAdapter | None = None,
        supervisor: SupervisorService | None = None,
        tool_authorization: ToolAuthorizationService | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.sessions = session_manager or coordinator.sessions
        self.worker_factory = worker_factory or WorkerFactory()
        self.worker_dispatcher = worker_dispatcher or WorkerDispatcher()
        self.worker_agent = worker_agent or CrewAIWorkerAdapter()
        self.worker_runtime = worker_runtime
        self.supervisor = supervisor or SupervisorService()
        self.tool_authorization = tool_authorization

    def execute_run(self, run_id: str) -> OrchestrationResult:
        """Execute dependency-safe batches, pausing for unresolved Gate C."""
        context = self.sessions.get_context(run_id)
        if context.state != WorkflowState.EXECUTING:
            raise IntegratedOrchestrationError(
                f"run {run_id} must be in EXECUTING, got {context.state.value}"
            )
        if self.worker_runtime is None:
            raise IntegratedOrchestrationError(
                "WorkerRuntimeAdapter has not been configured with an ExecutionGateway"
            )

        snapshot = self.sessions.snapshot(run_id)
        plan = snapshot.architecture_plan
        if plan is None:
            raise IntegratedOrchestrationError("run has no ArchitecturePlan")
        plan.validate()

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
            run_id=run_id, workers=workers, tasks=tasks
        )
        gate_a = self._execution_authorization(run_id)
        all_execution_results: list[ExecutionResult] = []

        for batch in batches:
            task_by_worker = {task.worker_id: task for task in batch.tasks}
            executable: list[tuple[WorkerInstance, Any, ExecutionAuthorization]] = []

            for worker in batch.workers:
                existing = self.sessions.snapshot(run_id).worker_outputs.get(worker.worker_id)
                if existing is not None and existing.status == "success":
                    continue

                task = task_by_worker.get(worker.worker_id)
                if task is None:
                    self._set_worker_error(
                        run_id, worker, "dispatcher produced no task for worker"
                    )
                    continue

                tool_decision = self._authorize_worker_tools(
                    run_id=run_id,
                    worker=worker,
                    required_capabilities=tuple(
                        getattr(plan, "required_capabilities", ()) or ()
                    ),
                )

                if tool_decision.gate_id is not None and tool_decision.authorization is None:
                    self.sessions.set_worker_output(
                        run_id,
                        WorkerOutput(
                            worker_id=worker.worker_id,
                            run_id=run_id,
                            status="waiting_human",
                            output={
                                "gate": "TOOL_RISK",
                                "gate_id": tool_decision.gate_id,
                                "required_tools": list(worker.required_tools),
                                "resolved_tools": [
                                    tool.tool_id for tool in tool_decision.resolved_tools
                                ],
                            },
                        ),
                    )
                    self.sessions.add_message(
                        run_id,
                        role="system",
                        content=(
                            f"Worker {worker.worker_id} is paused pending human Gate C approval "
                            "for risky tool access."
                        ),
                        metadata={
                            "phase": "tool_authorization",
                            "gate_id": tool_decision.gate_id,
                            "worker_id": worker.worker_id,
                        },
                    )
                    self.sessions.transition(run_id, WorkflowState.WORKER_WAITING_HUMAN)
                    return OrchestrationResult(
                        run_id=run_id,
                        batches=batches,
                        execution_results=tuple(all_execution_results),
                        qa_result=None,
                        pending_gate_id=tool_decision.gate_id,
                        pending_worker_id=worker.worker_id,
                    )

                authorization = tool_decision.authorization or gate_a
                try:
                    execution_plan = self.worker_agent.build_execution_plan(
                        worker=worker,
                        task=task,
                        context={
                            "run_id": run_id,
                            "objective": plan.objective,
                            "acceptance_criteria": list(plan.acceptance_criteria),
                            "authorized_tools": [
                                tool.tool_id for tool in tool_decision.resolved_tools
                            ],
                        },
                    )
                    executable.append((worker, execution_plan, authorization))
                except (RuntimeError, ValueError) as exc:
                    self._set_worker_error(
                        run_id, worker, f"{type(exc).__name__}: {exc}"
                    )

            if not executable:
                continue

            runtime_tasks = tuple(item[1].execution_task for item in executable)
            authorizations = {item[0].worker_id: item[2] for item in executable}
            shared_gate_ids = {authorization.gate_id for authorization in authorizations.values()}
            try:
                if len(shared_gate_ids) == 1:
                    results = self.worker_runtime.execute_batch(
                        batch=DispatchBatch(
                            run_id=batch.run_id,
                            workers=tuple(item[0] for item in executable),
                            tasks=tuple(item[1].execution_task.task for item in executable),
                            sequence=batch.sequence,
                        ),
                        tasks=runtime_tasks,
                        authorization=next(iter(authorizations.values())),
                        parallel=len(runtime_tasks) > 1,
                    )
                else:
                    collected: list[ExecutionResult] = []
                    for worker, execution_plan, authorization in executable:
                        collected.extend(
                            self.worker_runtime.execute_batch(
                                batch=DispatchBatch(
                                    run_id=batch.run_id,
                                    workers=(worker,),
                                    tasks=(execution_plan.execution_task.task,),
                                    sequence=batch.sequence,
                                ),
                                tasks=(execution_plan.execution_task,),
                                authorization=authorization,
                            )
                        )
                    results = tuple(collected)
            except (WorkerRuntimeError, RuntimeError, ValueError) as exc:
                error = f"{type(exc).__name__}: {exc}"
                for worker, _execution_plan, _authorization in executable:
                    self._set_worker_error(run_id, worker, error)
                continue

            all_execution_results.extend(results)
            for (worker, execution_plan, _authorization), result in zip(executable, results):
                self.sessions.set_worker_output(
                    run_id,
                    WorkerOutput(
                        worker_id=worker.worker_id,
                        run_id=run_id,
                        status=(
                            "success" if result.status.value == "success" else result.status.value
                        ),
                        output={
                            "summary": execution_plan.summary,
                            "authorized_tools": list(worker.required_tools),
                            "execution": to_dict(result),
                        },
                    ),
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

        final_gate_id: str | None = None
        if qa.status == QAStatus.PASS:
            final_gate_id = self.coordinator.record_supervisor_result(qa)
        else:
            self.sessions.transition(run_id, WorkflowState.REVISION)

        return OrchestrationResult(
            run_id=run_id,
            batches=batches,
            execution_results=tuple(all_execution_results),
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
        """Resolve Gate C and resume or reject the paused worker lifecycle."""
        context = self.sessions.get_context(run_id)
        if context.state != WorkflowState.WORKER_WAITING_HUMAN:
            raise IntegratedOrchestrationError(
                f"tool-gate resume requires WORKER_WAITING_HUMAN, got {context.state.value}"
            )
        if self.tool_authorization is None:
            raise IntegratedOrchestrationError("ToolAuthorizationService is not configured")

        authorization = self.tool_authorization.resolve_gate(
            gate_id=gate_id,
            decision=decision,
            run_id=run_id,
            worker_id=worker_id,
            feedback=feedback,
            actor=actor,
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
            self.sessions.transition(run_id, WorkflowState.REVISION)
            return OrchestrationResult(
                run_id=run_id,
                batches=(),
                execution_results=(),
                qa_result=None,
            )

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
            )
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

    def _execution_authorization(self, run_id: str) -> ExecutionAuthorization:
        snapshot = self.sessions.snapshot(run_id)
        valid_approvals = []
        for decision in snapshot.decisions:
            if decision.decision != HumanDecisionType.APPROVE:
                continue
            gate = self.coordinator.approvals.get_gate(decision.gate_id)
            if (
                gate.run_id == run_id
                and gate.kind == "ARCHITECTURE"
                and gate.status == GateStatus.RESOLVED
            ):
                valid_approvals.append(gate)
        if not valid_approvals:
            raise IntegratedOrchestrationError(
                "no recorded human Gate-A approval is available for execution"
            )
        gate = valid_approvals[-1]
        return ExecutionAuthorization(
            authorized=True,
            reason="worker execution authorized by Gate A",
            gate_id=gate.gate_id,
        )
