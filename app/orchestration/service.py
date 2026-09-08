"""Integrated run orchestration across the runtime's bounded modules.

M15 is the coordinator that turns an approved ArchitecturePlan into worker
batches, asks the configured agent provider for execution plans, routes those
plans through M13/M08, records worker evidence, and invokes M09 QA.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.crewai_adapter import CrewAIWorkerAdapter
from app.core.contracts import ExecutionResult, HumanDecisionType, to_dict
from app.core.states import WorkflowState
from app.execution.models import ExecutionAuthorization
from app.session.manager import SessionManager
from app.session.models import WorkerOutput
from app.supervisor.models import QAResult, QAStatus, SupervisorInput
from app.supervisor.service import SupervisorService
from app.workers.models import DispatchBatch
from app.workers.runtime import WorkerRuntimeAdapter, WorkerRuntimeError
from app.workers.service import WorkerDispatcher, WorkerFactory
from app.runtime.service import RuntimeCoordinator


class IntegratedOrchestrationError(RuntimeError):
    """Raised when the integrated execution path cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Evidence produced by one end-to-end worker orchestration pass."""

    run_id: str
    batches: tuple[DispatchBatch, ...]
    execution_results: tuple[ExecutionResult, ...]
    qa_result: QAResult
    final_gate_id: str | None = None


class IntegratedOrchestrator:
    """Execute the post-Gate-A lifecycle without bypassing module boundaries."""

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
    ) -> None:
        self.coordinator = coordinator
        self.sessions = session_manager or coordinator.sessions
        self.worker_factory = worker_factory or WorkerFactory()
        self.worker_dispatcher = worker_dispatcher or WorkerDispatcher()
        self.worker_agent = worker_agent or CrewAIWorkerAdapter()
        self.worker_runtime = worker_runtime
        self.supervisor = supervisor or SupervisorService()

    def execute_run(self, run_id: str) -> OrchestrationResult:
        """Execute all dispatch batches and finish at QA or Gate D."""
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
            run_id=run_id,
            workers=workers,
            tasks=tasks,
        )

        approval = self._execution_authorization(run_id)
        all_execution_results: list[ExecutionResult] = []

        for batch in batches:
            task_by_worker = {task.worker_id: task for task in batch.tasks}
            for worker in batch.workers:
                task = task_by_worker.get(worker.worker_id)
                if task is None:
                    output = WorkerOutput(
                        worker_id=worker.worker_id,
                        run_id=run_id,
                        status="error",
                        output={"error": "dispatcher produced no task for worker"},
                    )
                    self.sessions.set_worker_output(run_id, output)
                    continue

                try:
                    execution_plan = self.worker_agent.build_execution_plan(
                        worker=worker,
                        task=task,
                        context={
                            "run_id": run_id,
                            "objective": plan.objective,
                            "acceptance_criteria": list(plan.acceptance_criteria),
                        },
                    )
                    results = self.worker_runtime.execute_batch(
                        batch=DispatchBatch(
                            run_id=batch.run_id,
                            workers=(worker,),
                            tasks=(task,),
                            sequence=batch.sequence,
                        ),
                        tasks=(execution_plan.execution_task,),
                        authorization=approval,
                    )
                    all_execution_results.extend(results)
                    result = results[-1]
                    status = "success" if result.status.value == "success" else result.status.value
                    evidence: Any = {
                        "summary": execution_plan.summary,
                        "execution": to_dict(result),
                    }
                except (WorkerRuntimeError, RuntimeError, ValueError) as exc:
                    status = "error"
                    evidence = {"error": f"{type(exc).__name__}: {exc}"}

                self.sessions.set_worker_output(
                    run_id,
                    WorkerOutput(
                        worker_id=worker.worker_id,
                        run_id=run_id,
                        status=status,
                        output=evidence,
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

    def _execution_authorization(self, run_id: str) -> ExecutionAuthorization:
        snapshot = self.sessions.snapshot(run_id)
        valid_approvals = []
        for decision in snapshot.decisions:
            if decision.decision != HumanDecisionType.APPROVE:
                continue
            gate = self.coordinator.approvals.get_gate(decision.gate_id)
            if gate.run_id == run_id and gate.kind == "ARCHITECTURE":
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
