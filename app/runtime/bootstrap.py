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
from app.execution import (
    ColabExecutionBackend,
    ColabExecutionReconciler,
    DockerExecutionBackend,
    ExecutionGateway,
    ExecutionReconciliationService,
)
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


def build_runtime(settings: Settings | None = None) -> RuntimeApplication:
    """Build one coherent runtime graph from environment-backed configuration."""
    settings = settings or get_settings()

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
    if settings.execution_gateway_url:
        backends.append(
            ColabExecutionBackend(
                base_url=settings.execution_gateway_url,
                token=settings.execution_gateway_token,
                timeout_seconds=settings.default_execution_timeout_seconds,
            )
        )
    backends.append(
        DockerExecutionBackend(
            allow_network=os.getenv("DOCKER_ALLOW_NETWORK", "false").strip().lower() == "true",
            artifact_root=os.getenv("DOCKER_ARTIFACT_ROOT") or None,
        )
    )
    gateway = ExecutionGateway(backends=tuple(backends), settings=settings)
    worker_runtime = WorkerRuntimeAdapter(gateway=gateway, session_manager=sessions)

    registry = ToolRegistry()
    tool_authorization = ToolAuthorizationService(registry=registry, approvals=approvals)
    orchestrator = IntegratedOrchestrator(
        coordinator=coordinator,
        session_manager=sessions,
        worker_factory=WorkerFactory(),
        worker_dispatcher=WorkerDispatcher(),
        worker_runtime=worker_runtime,
        worker_agent=CrewAIWorkerAdapter(settings),
        supervisor=SupervisorService(),
        tool_authorization=tool_authorization,
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
    )
