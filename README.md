# Universal Agent Runtime

Universal multi-agent runtime with explicit human-approval gates, provider-neutral execution, durable identity, persistence, and optional hardened container execution.

## Progress

M00–M26 are complete. M27–M29 complete the deferred execution-isolation, persistence, and cloud-validation layers.

- **M00–M26:** ✅ Foundation, lifecycle, intake, Gemini, Architect, human gates, workers, tools, execution gateway, Colab runtime, CrewAI, orchestration, persistence, authentication, concurrency, QA, deployment boundary, multi-user identity.
- **M27 — Stronger Docker Execution Isolation:** ✅ Optional Docker backend with network isolation by default, read-only root filesystem, dropped capabilities, no-new-privileges, resource limits, non-root execution, and bounded output.
- **M28 — Versioned Persistence:** ✅ Transactional SQLite migrations plus a durable JSON session repository with explicit schema versioning and atomic writes.
- **M29 — Live Cloud Validation:** ✅ Dependency-free smoke-test harness for a reachable M12 service, including health, authenticated execution, and authentication-boundary checks.

## Architecture

See `BLUEPRINT_MASTER_v1.md` for the master architecture and `docs/architecture/` plus the M26–M29 milestone documents for detailed boundaries.

```text
User / Chainlit
  -> M22/M26 Authentication + Durable Identity
  -> Run Ownership Authorization
  -> M02 Intake
  -> M04 Architect
  -> Gate A
  -> M06 Worker Factory / dependency batches
  -> M07 Tool Registry + M16 authorization
  -> Gate C when required
  -> M14 CrewAI worker adapter
  -> M13 Worker Runtime
  -> M08 Execution Gateway
  -> M12 Colab or M27 Docker backend
  -> Session evidence / durable persistence
  -> M09 Supervisor / QA
  -> Gate D
  -> Completed | Revision | Rejected
```

## Persistence

M21 provides a trusted-storage SQLite session repository using the stable `SessionRepository` boundary. M28 additionally provides schema-versioned migrations and a portable JSON session repository that reconstructs domain objects explicitly.

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
