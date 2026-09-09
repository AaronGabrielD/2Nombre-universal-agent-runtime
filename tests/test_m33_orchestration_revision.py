import unittest

from app.agents.crewai_adapter import WorkerExecutionPlan
from app.approval.service import HumanApprovalEngine
from app.core.contracts import ArchitecturePlan, ExecutionResult, ExecutionStatus, HumanDecisionType, RiskLevel, WorkerSpec
from app.core.states import WorkflowState
from app.execution import ExecutionBackend, ExecutionBackendInfo, ExecutionGateway
from app.intake.service import IntakeService
from app.orchestration.service import IntegratedOrchestrator
from app.runtime.service import RuntimeCoordinator
from app.session.manager import SessionManager
from app.supervisor.models import QAResult, QAStatus, SupervisorInput
from app.tools.authorization import ToolAuthorizationService
from app.tools.models import CapabilitySpec, ToolRegistration
from app.tools.service import ToolRegistry
from app.workers.runtime import WorkerExecutionTask, WorkerRuntimeAdapter


class RevisionBackend(ExecutionBackend):
    @property
    def info(self):
        return ExecutionBackendInfo("revision-test", "Revision Test")

    def execute(self, request):
        return ExecutionResult(
            execution_id=request.execution_id,
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
            backend="revision-test",
        )


class RevisionWorkerAgent:
    def build_execution_plan(self, *, worker, task, context=None):
        return WorkerExecutionPlan(
            worker_id=worker.worker_id,
            task_id=task.task_id,
            summary="revision test worker",
            execution_task=WorkerExecutionTask(
                task=task,
                language="python",
                code="print('ok')",
            ),
        )


class ReviseSupervisor:
    def evaluate(self, data: SupervisorInput) -> QAResult:
        return QAResult(
            run_id=data.run_id,
            status=QAStatus.REVISE,
            score=0.25,
            summary="Supervisor requires another pass.",
            findings=("missing evidence",),
            blocking_issues=("missing evidence",),
            recommended_action="revise_and_reexecute",
            evidence={"source": "test"},
        )


def settings():
    from app.core.config import Settings

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
        execution_backend="revision-test",
        execution_gateway_url=None,
        execution_gateway_token=None,
    )


def make_ready_run_with_plan(required_tools=()):
    sessions = SessionManager()
    approvals = HumanApprovalEngine()
    intake = IntakeService(session_manager=sessions, settings=settings())
    coordinator = RuntimeCoordinator(
        session_manager=sessions,
        intake_service=intake,
        approval_engine=approvals,
    )
    run = coordinator.start_run("Build a revision test")
    plan = ArchitecturePlan(
        plan_id="revision-plan",
        objective="Build a revision test",
        acceptance_criteria=("produce a successful execution",),
        workers=(
            WorkerSpec(
                worker_id="worker-1",
                role="builder",
                mission="produce the result",
                deliverables=("result",),
                required_tools=tuple(required_tools),
            ),
        ),
    )
    sessions.set_architecture_plan(run.run_id, plan)
    gate = approvals.request_gate(
        run_id=run.run_id,
        kind="ARCHITECTURE",
        title="Approve architecture",
        prompt="approve",
    )
    sessions.transition(run.run_id, WorkflowState.ARCHITECTING)
    sessions.transition(run.run_id, WorkflowState.WAITING_ARCHITECT_APPROVAL)
    decision = approvals.resolve_gate(
        gate_id=gate.gate_id,
        decision=HumanDecisionType.APPROVE,
        feedback="approved",
    )
    coordinator.apply_architecture_decision(decision)
    return coordinator, sessions, run.run_id, approvals


class M33OrchestrationRevisionTests(unittest.TestCase):
    def test_supervisor_revise_creates_durable_revision_and_reenters_architecting(self):
        coordinator, sessions, run_id, _ = make_ready_run_with_plan()
        gateway = ExecutionGateway(backends=(RevisionBackend(),), settings=settings())
        orchestrator = IntegratedOrchestrator(
            coordinator=coordinator,
            session_manager=sessions,
            worker_runtime=WorkerRuntimeAdapter(gateway=gateway, session_manager=sessions),
            worker_agent=RevisionWorkerAgent(),
            supervisor=ReviseSupervisor(),
        )

        result = orchestrator.execute_run(run_id)

        self.assertEqual(result.qa_result.status, QAStatus.REVISE)
        self.assertEqual(sessions.get_context(run_id).state, WorkflowState.ARCHITECTING)
        revisions = coordinator.list_revisions(run_id)
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].source, "supervisor")
        self.assertIn("Supervisor QA returned revise", revisions[0].reason)

    def test_gate_c_rejection_creates_revision_and_never_executes(self):
        coordinator, sessions, run_id, approvals = make_ready_run_with_plan(("dangerous-tool",))
        registry = ToolRegistry()
        registry.register_capability(CapabilitySpec("protected", "Protected", "Requires approval"))
        registry.register_tool(
            ToolRegistration(
                tool_id="dangerous-tool",
                name="Dangerous Tool",
                description="High-risk test tool",
                handler=lambda payload: payload,
                risk_level=RiskLevel.HIGH,
                requires_human_approval=True,
                capabilities=("protected",),
            )
        )
        tool_auth = ToolAuthorizationService(registry=registry, approvals=approvals)
        gateway = ExecutionGateway(backends=(RevisionBackend(),), settings=settings())
        orchestrator = IntegratedOrchestrator(
            coordinator=coordinator,
            session_manager=sessions,
            worker_runtime=WorkerRuntimeAdapter(gateway=gateway, session_manager=sessions),
            worker_agent=RevisionWorkerAgent(),
            tool_authorization=tool_auth,
        )

        paused = orchestrator.execute_run(run_id)
        rejected = orchestrator.resume_after_tool_gate(
            run_id=run_id,
            gate_id=paused.pending_gate_id,
            decision=HumanDecisionType.REJECT,
            worker_id="worker-1",
            feedback="tool use denied for this run",
        )

        self.assertIsNone(rejected.qa_result)
        self.assertEqual(sessions.get_context(run_id).state, WorkflowState.ARCHITECTING)
        revisions = coordinator.list_revisions(run_id)
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].source, "human")
        self.assertIn("authorization was denied", revisions[0].reason)
        self.assertEqual(sessions.snapshot(run_id).execution_results, [])


if __name__ == "__main__":
    unittest.main()
