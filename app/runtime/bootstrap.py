"""Composition root for the Universal Agent Runtime.

The bootstrap layer wires the already-defined bounded services into one runtime
application. Presentation layers should consume this composition root instead
of constructing providers, gateways, or authorization services themselves.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from app.agents.crewai_adapter import CrewAIWorkerAdapter
from app.approval.service import HumanApprovalEngine
from app.architect.service import UniversalArchitect
from app.core.config import Settings, get_settings
from app.core.contracts import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.execution import (
    ColabExecutionBackend,
    ColabExecutionReconciler,
    DockerExecutionBackend,
    ExecutionGateway,
    ExecutionReconciliationService,
)
from app.execution.models import ExecutionBackendInfo
from app.execution.service import ExecutionBackend
from app.identity import IdentityService, RunAuthorizationService, SQLiteUserRepository
from app.intake.service import IntakeService
from app.llm.gemini import GeminiAdapter
from app.orchestration.service import IntegratedOrchestrator
from app.recovery.resume import RecoveryResumeService
from app.session.manager import SessionManager
from app.supervisor.service import SupervisorService
from app.tools.authorization import ToolAuthorizationService
from app.tools.service import ToolRegistry
from app.workers.runtime import WorkerRuntimeAdapter
from app.workers.service import WorkerDispatcher, WorkerFactory

from .persistence import build_session_repository
from .service import RuntimeCoordinator


@dataclass(frozen=True, slots=True)
class RuntimeApplication:
    """Fully wired runtime services used by UI/API entrypoints."""

    coordinator: RuntimeCoordinator
    orchestrator: IntegratedOrchestrator
    sessions: SessionManager
    approvals: HumanApprovalEngine
    identity: IdentityService
    run_authorization: RunAuthorizationService
    tool_registry: ToolRegistry
    tool_authorization: ToolAuthorizationService
    execution_gateway: ExecutionGateway


class _UnavailableTestExecutionBackend(ExecutionBackend):
    """Non-executing backend used only to make test-mode composition explicit."""

    @property
    def info(self) -> ExecutionBackendInfo:
        return ExecutionBackendInfo(
            backend_id="test",
            name="Test backend (execution unavailable)",
            available=False,
        )

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(
            execution_id=request.execution_id,
            run_id=request.run_id,
            worker_id=request.worker_id,
            status=ExecutionStatus.UNAVAILABLE,
            exit_code=None,
            stdout="",
            stderr="test execution backend is intentionally unavailable",
            duration_ms=0,
            backend="test",
        )


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def build_runtime(
    settings: Settings | None = None,
    *,
    tool_registry: ToolRegistry | None = None,
) -> RuntimeApplication:
    """Build one coherent runtime graph from environment-backed configuration."""
    settings = settings or get_settings()
    settings.validate()

    sessions = SessionManager(repository=build_session_repository())
    approvals = HumanApprovalEngine(session_manager=sessions)
    intake = IntakeService(session_manager=sessions, settings=settings)
    architect = UniversalArchitect(GeminiAdapter(settings), settings=settings)

    reconciliation_service = ExecutionReconciliationService(session_manager=sessions)
    if settings.execution_gateway_url and settings.execution_gateway_token:
        reconciliation_service = ExecutionReconciliationService(
            session_manager=sessions,
            backend_reconciler=ColabExecutionReconciler(
                base_url=settings.execution_gateway_url,
                token=settings.execution_gateway_token,
            ),
        )

    recovery_resume = RecoveryResumeService(
        session_manager=sessions,
        reconciliation_service=reconciliation_service,
    )
    coordinator = RuntimeCoordinator(
        session_manager=sessions,
        intake_service=intake,
        architect=architect,
        approval_engine=approvals,
        recovery_resume_service=recovery_resume,
    )

    backends = []
    if settings.execution_gateway_url and settings.execution_backend == "colab":
        backends.append(
            ColabExecutionBackend(
                base_url=settings.execution_gateway_url,
                token=settings.execution_gateway_token,
                timeout_seconds=settings.default_execution_timeout_seconds,
            )
        )
    if settings.execution_backend == "test":
        backends.append(_UnavailableTestExecutionBackend())
    elif settings.execution_backend == "docker" or not backends:
        backends.append(
            DockerExecutionBackend(
                image=os.getenv("DOCKER_IMAGE", "python:3.12-alpine"),
                allow_network=os.getenv("DOCKER_ALLOW_NETWORK", "false").strip().lower() == "true",
                memory=os.getenv("DOCKER_MEMORY", "512m"),
                cpus=os.getenv("DOCKER_CPUS", "1.0"),
                pids_limit=_env_int("DOCKER_PIDS_LIMIT", 128, minimum=16),
                max_output_bytes=_env_int("DOCKER_MAX_OUTPUT_BYTES", 256 * 1024, minimum=1024),
                artifact_root=os.getenv("DOCKER_ARTIFACT_ROOT") or None,
                max_artifacts=_env_int("DOCKER_MAX_ARTIFACTS", 20, minimum=1),
                max_artifact_bytes=_env_int(
                    "DOCKER_MAX_ARTIFACT_BYTES", 10 * 1024 * 1024, minimum=1
                ),
                max_total_artifact_bytes=_env_int(
                    "DOCKER_MAX_TOTAL_ARTIFACT_BYTES", 32 * 1024 * 1024, minimum=1
                ),
            )
        )
    gateway = ExecutionGateway(backends=tuple(backends), settings=settings)
    worker_runtime = WorkerRuntimeAdapter(gateway=gateway, session_manager=sessions, settings=settings)

    registry = tool_registry or ToolRegistry()
    tool_authorization = ToolAuthorizationService(
        registry=registry,
        approvals=approvals,
        settings=settings,
    )
    orchestrator = IntegratedOrchestrator(
        coordinator=coordinator,
        session_manager=sessions,
        worker_factory=WorkerFactory(),
        worker_dispatcher=WorkerDispatcher(),
        worker_runtime=worker_runtime,
        worker_agent=CrewAIWorkerAdapter(settings),
        supervisor=SupervisorService(),
        tool_authorization=tool_authorization,
        settings=settings,
    )

    identity = IdentityService(
        SQLiteUserRepository(os.getenv("UAR_IDENTITY_DB_PATH", "runtime_users.db"))
    )
    return RuntimeApplication(
        coordinator=coordinator,
        orchestrator=orchestrator,
        sessions=sessions,
        approvals=approvals,
        identity=identity,
        run_authorization=RunAuthorizationService(),
        tool_registry=registry,
        tool_authorization=tool_authorization,
        execution_gateway=gateway,
    )
