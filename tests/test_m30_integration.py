import unittest

from app.agents.crewai_adapter import WorkerExecutionPlan
from app.approval.service import HumanApprovalEngine
from app.core.config import Settings
from app.core.contracts import (
    ArchitecturePlan,
    ExecutionResult,
    ExecutionStatus,
    HumanDecisionType,
    RiskLevel,
    WorkerSpec,
)
from app.core.states import WorkflowState
from app.execution import ExecutionBackend, ExecutionBackendInfo, ExecutionGateway
from app.identity import RunAuthorizationService
from app.intake.service import IntakeService
from app.orchestration.service import IntegratedOrchestrator
from app.runtime.bootstrap import build_runtime
from app.runtime.service import RuntimeCoordinator
from app.session.manager import SessionManager
from app.tools.authorization import ToolAuthorizationService
from app.tools.models import ToolRegistration
from app.tools.service import ToolRegistry
from app.workers.runtime import WorkerExecutionTask, WorkerRuntimeAdapter


class _Backend(ExecutionBackend):
    @property
    def info(self):
        return ExecutionBackendInfo("test", "Test")

    def execute(self, request):
        return ExecutionResult(
            execution_id=request.execution_id,
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout=request.worker_id,
            stderr="",
            duration_ms=1,
            backend="test",
        )


class _Agent:
    def build_execution_plan(self, *, worker, task, context=None):
        return WorkerExecutionPlan(
            worker_id=worker.worker_id,
            task_id=task.task_id,
            summary="generated",
            execution_task=WorkerExecutionTask(
                task=task,
                language="python",
                code="print('ok')",
            ),
        )


def _settings():
    return Settings(
        gemini_api_key="test-key",
        gemini_model_architect="architect",
        gemini_model_worker="worker",
        gemini_model_supervisor="supervisor",
        gemini_temperature=0.2,
        max_workers=4,
        min_workers=3,
        default_execution_timeout_seconds=60,
        max_uploads_per_message=20,
        max_upload_size_mb=100,
        execution_backend="test",
        execution_gateway_url=None,
        execution_gateway_token=None,
    )


class M30IntegrationTests(unittest.TestCase):
    def test_independent_worker_runs_while_other_worker_waits_for_gate_c(self):
        settings = _settings()
        sessions = SessionManager()
        approvals = HumanApprovalEngine()
        coordinator = RuntimeCoordinator(
            session_manager=sessions,
            intake_service=IntakeService(session_manager=sessions, settings=settings),
            approval_engine=approvals,
        )
        run = coordinator.start_run("build two independent workers")
        plan = ArchitecturePlan(
            plan_id="plan-m30",
            objective=run.run_id,
            acceptance_criteria=("workers execute",),
            workers=(
                WorkerSpec(
                    worker_id="safe-worker",
                    role="builder",
                    mission="build safely",
                ),
                WorkerSpec(
                    worker_id="risky-worker",
                    role="builder",
                    mission="use risky capability",
                    required_tools=("risky_tool",),
                ),
            ),
        )
        sessions.set_architecture_plan(run.run_id, plan)
        gate_a = approvals.request_gate(
            run_id=run.run_id,
            kind="ARCHITECTURE",
            title="Architecture",
            prompt="approve",
        )
        sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
        sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
        decision = approvals.resolve_gate(
            gate_id=gate_a.gate_id,
            decision=HumanDecisionType.APPROVE,
            feedback="approved",
        )
        coordinator.apply_architecture_decision(decision)

        registry = ToolRegistry()
        registry.register_tool(
            ToolRegistration(
                tool_id="risky_tool",
                name="Risky tool",
                description="test risky tool",
                handler=lambda _payload: None,
                risk_level=RiskLevel.HIGH,
                requires_human_approval=True,
            )
        )
        gateway = ExecutionGateway(backends=(_Backend(),), settings=settings)
        orchestrator = IntegratedOrchestrator(
            coordinator=coordinator,
            session_manager=sessions,
            worker_runtime=WorkerRuntimeAdapter(gateway=gateway, session_manager=sessions),
            worker_agent=_Agent(),
            tool_authorization=ToolAuthorizationService(registry=registry, approvals=approvals),
        )

        result = orchestrator.execute_run(run.run_id)

        self.assertIsNone(result.qa_result)
        self.assertIsNotNone(result.pending_gate_id)
        self.assertEqual(result.pending_worker_id, "risky-worker")
        self.assertEqual(len(result.execution_results), 1)
        self.assertEqual(result.execution_results[0].stdout, "safe-worker")
        self.assertEqual(
            sessions.snapshot(run.run_id).worker_outputs["safe-worker"].status,
            "success",
        )
        self.assertEqual(
            sessions.get_context(run.run_id).state,
            WorkflowState.WORKER_WAITING_HUMAN,
        )

    def test_run_authorization_is_exposed_by_composition_root(self):
        application = build_runtime(_settings())
        self.assertIsInstance(application.run_authorization, RunAuthorizationService)
        self.assertIs(application.coordinator.sessions, application.sessions)
        self.assertIs(application.approvals, application.coordinator.approvals)


if __name__ == "__main__":
    unittest.main()
