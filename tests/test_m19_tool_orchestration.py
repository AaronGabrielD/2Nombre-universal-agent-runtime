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
from app.intake.service import IntakeService
from app.orchestration.service import IntegratedOrchestrator
from app.runtime.service import RuntimeCoordinator
from app.session.manager import SessionManager
from app.tools.authorization import ToolAuthorizationError, ToolAuthorizationService
from app.tools.models import CapabilitySpec, ToolRegistration
from app.tools.service import ToolRegistry
from app.workers.runtime import WorkerExecutionTask, WorkerRuntimeAdapter


class CountingBackend(ExecutionBackend):
    calls = 0

    @property
    def info(self):
        return ExecutionBackendInfo("test", "Test")

    def execute(self, request):
        type(self).calls += 1
        return ExecutionResult(
            execution_id=request.execution_id,
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
            backend="test",
        )


class FakeWorkerAgent:
    def build_execution_plan(self, *, worker, task, context=None):
        return WorkerExecutionPlan(
            worker_id=worker.worker_id,
            task_id=task.task_id,
            summary="generated after authorization",
            execution_task=WorkerExecutionTask(
                task=task,
                language="python",
                code="print('ok')",
            ),
        )


def settings():
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


def make_risky_orchestrator():
    sessions = SessionManager()
    approvals = HumanApprovalEngine()
    intake = IntakeService(session_manager=sessions, settings=settings())
    coordinator = RuntimeCoordinator(
        session_manager=sessions,
        intake_service=intake,
        approval_engine=approvals,
    )
    run = coordinator.start_run("Build a protected project")
    plan = ArchitecturePlan(
        plan_id="plan-risky",
        objective="Build a protected project",
        acceptance_criteria=("produce a successful execution",),
        workers=(
            WorkerSpec(
                worker_id="worker-risky",
                role="builder",
                mission="use the protected tool",
                deliverables=("result",),
                required_tools=("dangerous-tool",),
            ),
        ),
    )
    sessions.set_architecture_plan(run.run_id, plan)
    gate_a = approvals.request_gate(
        run_id=run.run_id,
        kind="ARCHITECTURE",
        title="Approve architecture",
        prompt="approve",
    )
    sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
    sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
    decision_a = approvals.resolve_gate(
        gate_id=gate_a.gate_id,
        decision=HumanDecisionType.APPROVE,
        feedback="approved",
    )
    coordinator.apply_architecture_decision(decision_a)

    registry = ToolRegistry()
    registry.register_capability(
        CapabilitySpec("protected", "Protected", "A capability requiring explicit review")
    )
    registry.register_tool(
        ToolRegistration(
            tool_id="dangerous-tool",
            name="Dangerous Tool",
            description="A high-risk declarative test tool",
            handler=lambda payload: payload,
            risk_level=RiskLevel.HIGH,
            requires_human_approval=True,
            capabilities=("protected",),
        )
    )
    tool_auth = ToolAuthorizationService(registry=registry, approvals=approvals)
    gateway = ExecutionGateway(backends=(CountingBackend(),), settings=settings())
    runtime = WorkerRuntimeAdapter(gateway=gateway, session_manager=sessions)
    orchestrator = IntegratedOrchestrator(
        coordinator=coordinator,
        session_manager=sessions,
        worker_runtime=runtime,
        worker_agent=FakeWorkerAgent(),
        tool_authorization=tool_auth,
    )
    return orchestrator, sessions, run.run_id, approvals


class M19ToolOrchestrationTests(unittest.TestCase):
    def setUp(self):
        CountingBackend.calls = 0

    def test_risky_tool_pauses_before_execution(self):
        orchestrator, sessions, run_id, approvals = make_risky_orchestrator()

        result = orchestrator.execute_run(run_id)

        self.assertIsNone(result.qa_result)
        self.assertIsNotNone(result.pending_gate_id)
        self.assertEqual(result.pending_worker_id, "worker-risky")
        self.assertEqual(
            sessions.get_context(run_id).state,
            WorkflowState.WORKER_WAITING_HUMAN,
        )
        self.assertEqual(CountingBackend.calls, 0)
        gate = approvals.get_gate(result.pending_gate_id)
        self.assertEqual(gate.kind, "TOOL_RISK")
        self.assertEqual(gate.context["worker_id"], "worker-risky")

    def test_approved_gate_c_resumes_exact_worker(self):
        orchestrator, sessions, run_id, _approvals = make_risky_orchestrator()
        paused = orchestrator.execute_run(run_id)

        resumed = orchestrator.resume_after_tool_gate(
            run_id=run_id,
            gate_id=paused.pending_gate_id,
            decision=HumanDecisionType.APPROVE,
            worker_id="worker-risky",
            feedback="approved for this run",
        )

        self.assertIsNotNone(resumed.qa_result)
        self.assertEqual(resumed.qa_result.status.value, "pass")
        self.assertIsNotNone(resumed.final_gate_id)
        self.assertEqual(
            sessions.get_context(run_id).state,
            WorkflowState.WAITING_FINAL_APPROVAL,
        )
        self.assertEqual(CountingBackend.calls, 1)

    def test_rejected_gate_c_stops_run_without_execution(self):
        orchestrator, sessions, run_id, _approvals = make_risky_orchestrator()
        paused = orchestrator.execute_run(run_id)

        rejected = orchestrator.resume_after_tool_gate(
            run_id=run_id,
            gate_id=paused.pending_gate_id,
            decision=HumanDecisionType.REJECT,
            worker_id="worker-risky",
            feedback="tool not approved",
        )

        self.assertIsNone(rejected.qa_result)
        self.assertEqual(
            sessions.get_context(run_id).state,
            WorkflowState.REVISION,
        )
        self.assertEqual(CountingBackend.calls, 0)

    def test_unknown_tool_fails_closed(self):
        orchestrator, sessions, run_id, _approvals = make_risky_orchestrator()
        plan = sessions.snapshot(run_id).architecture_plan
        replacement = ArchitecturePlan(
            plan_id=plan.plan_id,
            objective=plan.objective,
            acceptance_criteria=plan.acceptance_criteria,
            workers=(
                WorkerSpec(
                    worker_id="worker-risky",
                    role="builder",
                    mission="use missing tool",
                    deliverables=("result",),
                    required_tools=("missing-tool",),
                ),
            ),
        )
        sessions.set_architecture_plan(run_id, replacement)

        with self.assertRaises(ToolAuthorizationError):
            orchestrator.execute_run(run_id)
        self.assertEqual(CountingBackend.calls, 0)


if __name__ == "__main__":
    unittest.main()
