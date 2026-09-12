import unittest

from app.agents.crewai_adapter import WorkerExecutionPlan
from app.approval.service import HumanApprovalEngine
from app.core.contracts import ArchitecturePlan, ExecutionResult, ExecutionStatus, HumanDecisionType, WorkerSpec
from app.core.states import WorkflowState
from app.execution import ExecutionBackend, ExecutionBackendInfo, ExecutionGateway
from app.intake.service import IntakeService
from app.orchestration.service import IntegratedOrchestrator
from app.runtime.service import RuntimeCoordinator
from app.session.manager import SessionManager
from app.supervisor.service import SupervisorService
from app.workers.runtime import WorkerExecutionTask, WorkerRuntimeAdapter


class SuccessBackend(ExecutionBackend):
    @property
    def info(self):
        return ExecutionBackendInfo("integration-test", "Integration Test")

    def execute(self, request):
        return ExecutionResult(
            execution_id=request.execution_id,
            run_id=request.run_id,
            worker_id=request.worker_id,
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="INTEGRATION_OK",
            stderr="",
            duration_ms=1,
            backend="integration-test",
        )


class SuccessWorkerAgent:
    def build_execution_plan(self, *, worker, task, context=None):
        return WorkerExecutionPlan(
            worker_id=worker.worker_id,
            task_id=task.task_id,
            summary="integration success worker",
            execution_task=WorkerExecutionTask(
                task=task,
                language="python",
                code="print('INTEGRATION_OK')",
            ),
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
        min_workers=1,
        default_execution_timeout_seconds=60,
        max_uploads_per_message=20,
        max_upload_size_mb=100,
        execution_backend="integration-test",
        execution_gateway_url=None,
        execution_gateway_token=None,
        execution_authorization_secret="test-execution-authorization-secret-1234567890",
    )


class IntegratedSuccessPathTests(unittest.TestCase):
    def test_gate_a_to_execution_to_qa_to_gate_d_to_completed(self):
        settings_value = settings()
        sessions = SessionManager()
        approvals = HumanApprovalEngine()
        intake = IntakeService(session_manager=sessions, settings=settings_value)
        supervisor = SupervisorService()
        coordinator = RuntimeCoordinator(
            session_manager=sessions,
            intake_service=intake,
            approval_engine=approvals,
            supervisor=supervisor,
        )
        run = coordinator.start_run("Build an integration test")
        plan = ArchitecturePlan(
            plan_id="integration-plan",
            objective="Build an integration test",
            acceptance_criteria=("produce a successful execution",),
            workers=(
                WorkerSpec(
                    worker_id="worker-1",
                    role="builder",
                    mission="produce the integration result",
                    deliverables=("result",),
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
        decision = approvals.resolve_gate(
            gate_id=gate_a.gate_id,
            decision=HumanDecisionType.APPROVE,
            feedback="approved",
        )
        self.assertEqual(coordinator.apply_architecture_decision(decision), WorkflowState.EXECUTING)

        gateway = ExecutionGateway(backends=(SuccessBackend(),), settings=settings_value)
        orchestrator = IntegratedOrchestrator(
            coordinator=coordinator,
            session_manager=sessions,
            worker_runtime=WorkerRuntimeAdapter(
                gateway=gateway,
                session_manager=sessions,
                settings=settings_value,
            ),
            worker_agent=SuccessWorkerAgent(),
            supervisor=supervisor,
        )

        result = orchestrator.execute_run(run.run_id)

        self.assertEqual(len(result.execution_results), 1)
        self.assertEqual(result.execution_results[0].status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.execution_results[0].stdout, "INTEGRATION_OK")
        self.assertEqual(result.qa_result.status.value, "pass")
        self.assertIsNotNone(result.final_gate_id)
        self.assertEqual(
            sessions.get_context(run.run_id).state,
            WorkflowState.WAITING_FINAL_APPROVAL,
        )

        final_decision = approvals.resolve_gate(
            gate_id=result.final_gate_id,
            decision=HumanDecisionType.APPROVE,
            feedback="approved",
        )
        final_state = coordinator.apply_final_decision(final_decision)

        self.assertEqual(final_state, WorkflowState.COMPLETED)
        final_snapshot = sessions.snapshot(run.run_id)
        self.assertEqual(len(final_snapshot.execution_results), 1)
        self.assertIsNotNone(final_snapshot.final_result)
        self.assertEqual(final_snapshot.final_result.run_id, run.run_id)


if __name__ == "__main__":
    unittest.main()
