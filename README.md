# Universal Agent Runtime

Universal multi-agent runtime with explicit human-approval gates, provider-neutral execution, durable identity, persistence, recovery controls, and optional hardened container execution.

## Progress

M00–M46 are integrated on `main` with automated CI coverage. Environment-specific live validation that requires external endpoints or credentials remains intentionally deferred.

- **M00–M26:** ✅ Foundation, lifecycle, intake, Gemini, Architect, human gates, workers, tools, execution gateway, Colab runtime, CrewAI, orchestration, persistence, authentication, concurrency, QA, deployment boundary, and multi-user identity.
- **M27 — Stronger Docker Execution Isolation:** ✅ Optional Docker backend with network isolation by default, read-only root filesystem, dropped capabilities, no-new-privileges, resource limits, non-root execution, and bounded output.
- **M28 — Versioned Persistence:** ✅ Transactional SQLite migrations plus a durable JSON session repository with explicit schema versioning and atomic writes.
- **M29 — Live Cloud Validation:** ✅ Dependency-free smoke-test harness for a reachable M12 service; live execution still depends on an available endpoint and credentials.
- **M30–M31:** ✅ Integrated runtime composition and hardened provider-neutral core contracts.
- **M32–M36:** ✅ Revision tracking, orchestration-wide revision routing, revision limits, restart recovery discovery, and explicit recovery checkpoints.
- **M37–M39:** ✅ Durable execution leases, replay protection, local evidence reconciliation, and explicit authoritative-backend reconciliation.
- **M40–M45:** ✅ Explicit recovery actions, durable recovery audit trail, runtime recovery facade, Colab authoritative reconciliation, explicit persistence selection, and authenticated Chainlit recovery surface.
- **M46:** ✅ Recovery state-machine integrity hardening and run-wide execution reconciliation.

## Architecture

See `BLUEPRINT_MASTER_v1.md` for the master architecture and `docs/architecture/` plus the milestone documents for detailed boundaries.

```text
User / Chainlit
  -> Authentication + Run Authorization
  -> Intake
  -> Architect
  -> Gate A
  -> Worker Factory / Dispatcher
  -> CrewAI Worker Adapter
  -> Tool Registry + Authorization
      -> Gate C when required
  -> Execution Gateway
      -> Colab HTTP backend
      -> Docker backend
  -> Supervisor / QA
  -> Gate D
  -> Completed | Revision | Rejected

Restart recovery:
  -> durable SessionRepository
  -> recoverable-run discovery
  -> recovery inspection
  -> explicit RecoveryAction
  -> RuntimeCoordinator
  -> reconciliation / revision routing as required
  -> durable recovery audit
  -> no automatic replay
```

## Persistence and recovery

The runtime supports explicit `SessionRepository` selection for process-local memory, durable JSON, or SQLite persistence. Restart recovery is fail-closed: persisted workflow state is inspected first, execution evidence is reconciled explicitly, and uncertain execution is never silently replayed.

## Execution isolation

M23 remains the static Python admission policy for the Colab service. M27 adds Docker isolation when a Docker daemon and preloaded image are available. The Docker backend never pulls an image automatically.

Neither mechanism should be treated as a high-assurance hostile multi-tenant sandbox; deployment and host hardening remain part of the security boundary.

## Cloud validation

Run the M29 external smoke harness against an actual reachable runtime service:

```bash
python scripts/m29_cloud_smoke.py
```

Configure `UAR_SMOKE_BASE_URL` and `RUNTIME_EXECUTION_TOKEN` without committing secrets. The repository does not fabricate a live Colab/Gemini pass when those external credentials/endpoints are unavailable.

## CrewAI integration

Install the optional CrewAI integration with:

```bash
pip install -r requirements-crewai.txt
```

CrewAI remains a worker-planning adapter; execution and human approval stay behind the runtime's authoritative boundaries.

## Security rule

Never commit `.env`, API keys, tokens, credentials, local databases, or runtime artifacts.
