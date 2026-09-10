# Implementation status

M00–M45 are implemented in `main` with automated CI coverage. M46 is proposed in PR #63 and is pending CI validation before integration. Environment-specific live validation that requires external endpoints or credentials remains intentionally deferred.

Current integrated path:

```text
User / Chainlit
  -> Auth + Run Authorization
  -> Intake
  -> Architect
  -> Gate A (Human)
  -> Worker Factory / Dispatcher
  -> CrewAI Worker Adapter
  -> Tool Authorization
      -> Gate C (Human) when required
  -> Execution Gateway
      -> Docker backend (local hardened option)
      -> Colab HTTP backend (remote option)
  -> Supervisor / QA
  -> Gate D (Human)
  -> Completed | Revision | Rejected

Revision path:
  -> RevisionService (reason/source/feedback/attempt/limit)
  -> ARCHITECTING
  -> new architecture approval cycle

Restart recovery path:
  -> persisted SessionRepository
  -> SessionManager.list_recoverable_sessions()
  -> RecoveryService.inspect()
  -> RuntimeCoordinator.inspect_recovery()
  -> explicit RuntimeCoordinator.resume_recovery()
  -> durable recovery action audit event
  -> no automatic execution/replay

Execution replay protection:
  -> ExecutionLeaseService
  -> deterministic idempotency key
  -> RUNNING lease blocks duplicate replay
  -> COMPLETED lease reuses persisted execution result

Execution reconciliation:
  -> RunExecutionReconciliationService [M46 proposal]
  -> latest durable lease for every task
  -> local durable evidence inspection
  -> explicit backend authority when configured
  -> authoritative result persisted locally
  -> deterministic ordering
  -> no implicit remote calls or retry

Runtime persistence:
  -> explicit SessionRepository selection
  -> memory | JSON | SQLite
  -> RuntimeComposition uses selected repository

Chainlit recovery surface:
  -> authenticated recoverable-run discovery
  -> explicit RecoveryAction selection
  -> EXECUTING requires original idempotency key
  -> human-gated states remain paused
```

## Milestones

- M00 — Foundation & Contracts
- M01 — Session Manager
- M02 — Universal Intake
- M03 — Gemini Adapter
- M04 — Universal Architect
- M05 — Human Approval Engine
- M06 — Worker Factory & Dispatcher
- M07 — Tool Registry & Capability Registry
- M08 — Execution Gateway
- M09 — Supervisor & QA
- M10 — Runtime Coordinator
- M11 — Chainlit Presentation
- M12 — Colab Execution Service
- M13 — Worker Runtime Adapter
- M14 — CrewAI Worker Adapter
- M15 — Integrated Orchestrator
- M16 — Tool Authorization + Gate C
- M17 — Session Concurrency
- M18 — Controlled Parallel Workers
- M19 — Tool Registry orchestration + Gate C pause/resume
- M20 — HTTP integration tests
- M21 — Persistent session storage
- M22 — Chainlit auth hardening
- M23 — execution policy
- M24 — CI
- M25 — provider-neutral deployment adapter
- M26 — multi-user durable identity/authorization
- M27 — Stronger Docker execution isolation backend
- M28 — Schema-versioned persistence migrations + JSON durable session backend
- M29 — Live cloud smoke-validation harness
- M30 — Integrated runtime composition + Chainlit orchestration
- M31 — Hardened provider-neutral core contracts
- M32 — Revision tracking + recovery loop
- M33 — Orchestration-wide revision integration
- M34 — Revision limits and recovery-loop hardening
- M35 — Durable session discovery for restart recovery
- M36 — Explicit post-restart recovery checkpoints
- M37 — Durable execution leases and replay protection
- M38 — Execution reconciliation from durable evidence
- M39 — Explicit authoritative backend reconciliation contract
- M40 — Explicit recovery resume actions
- M41 — Durable recovery action audit trail
- M42 — RuntimeCoordinator recovery facade
- M43 — Colab authoritative reconciliation client
- M44 — Explicit durable runtime session persistence selection
- M45 — Authenticated Chainlit recovery surface and runtime authority wiring
- M46 — Run-wide execution reconciliation (PR #63, pending validation)

## Revision and recovery hardening

M32 adds explicit revision records and durable history. M33 routes recoverable Supervisor QA revisions and Gate C denials through `RuntimeCoordinator` and `RevisionService`, returning the run to `ARCHITECTING` instead of mutating `REVISION` directly. M34 adds a per-service configurable revision ceiling (default 3) and rejects additional revision requests before mutating workflow state. M35 adds repository-wide session enumeration and `SessionManager.list_recoverable_sessions()` so a new process can discover non-terminal runs from SQLite, JSON, or in-memory storage without automatically executing anything. M36 adds explicit recovery checkpoints that classify persisted state and evidence without replaying worker execution or bypassing human gates.

M37 adds a durable execution lease for every worker task. A deterministic idempotency key identifies the same run/worker/task/code combination. An active lease blocks a second execution attempt, while a completed lease reuses the persisted execution result instead of invoking the backend again.

M38 adds an execution reconciliation layer that correlates a durable lease with persisted `ExecutionResult` evidence. A task is only locally classified as completed or failed when a matching durable result exists. An active lease without a result becomes `PENDING_BACKEND_CHECK`; the runtime does not silently retry it.

M39 adds an explicit provider-neutral `ExecutionReconciler` contract. `ExecutionReconciliationService.reconcile_backend()` may query a configured backend authority only when called explicitly, rejects inconsistent execution identifiers, persists returned authoritative evidence, and refuses retry when the backend is unavailable or cannot produce a result.

M40 adds `RecoveryResumeService`, which makes post-restart recovery executable only through an explicit `RecoveryAction`. Architecture rebuilds may return `REVISION` to `ARCHITECTING`; supervision can only resume from `SUPERVISING`; execution recovery requires an idempotency key and first reconciles durable evidence before optionally consulting an explicitly configured backend authority. Ambiguous or terminal recovery actions are rejected.

M41 adds a durable audit event to every accepted explicit recovery action. The event records the action, previous state, resulting state, and, when execution reconciliation is involved, the reconciliation status and execution ID. The audit entry is stored through the existing `SessionManager`, so SQLite/JSON session persistence retains the recovery trail after process recreation. Failed or ambiguous recovery requests remain fail-closed and do not create misleading accepted-action events.

M42 exposes recovery inspection and explicit resume through `RuntimeCoordinator`, keeping restart recovery behind the application's canonical coordination boundary. Callers no longer need to construct recovery services directly, while the underlying action validation, reconciliation, audit trail, and fail-closed behavior remain unchanged.

M43 adds `ColabExecutionReconciler`, a concrete HTTP implementation of the provider-neutral `ExecutionReconciler`. It authenticates to a protected execution-authority endpoint, queries by exact `execution_id`, sends the recovery `idempotency_key` as correlation metadata, treats HTTP 404 as absence of authoritative evidence, validates the complete `ExecutionResult` payload, and never executes code.

M44 adds explicit persistence selection to the runtime composition root. The application can use process-local memory for development compatibility, durable JSON for portable file-based deployments, or trusted SQLite storage. The persistence choice is configuration-driven through `UAR_SESSION_REPOSITORY` and `UAR_SESSION_REPOSITORY_PATH`; the bootstrap layer injects the selected repository into `SessionManager` instead of silently creating an in-memory store.

M45 adds an authenticated Chainlit recovery surface that discovers recoverable sessions for the logged-in user, exposes the canonical `RecoveryAction` as a UI action, delegates all state changes to `RuntimeCoordinator.resume_recovery()`, and never executes ambiguous recovery automatically. M45 also wires `ColabExecutionReconciler` into the runtime composition when execution-gateway credentials are configured, so explicit recovery can reach the authoritative backend through the existing provider-neutral contract.

M46 adds `RunExecutionReconciliationService`, which enumerates the latest durable execution lease for each task in a run, orders them deterministically, inspects local evidence without backend calls, and explicitly reconciles unresolved leases only when `reconcile_backend()` is invoked. Existing local evidence is always preferred; absent authority remains pending and never authorizes retry or fresh execution.

## Security and deployment boundaries

- M27 provides container-level defense in depth when Docker is available; it is not a high-assurance VM boundary.
- M23 execution policy is defense in depth, not a sandbox.
- M22 authentication and M26 run authorization are application-layer controls.
- M25 remains provider-neutral deployment rendering; it does not provision third-party infrastructure automatically.
- Direct tool handlers remain declarative and execution stays behind M08.
- M36 deliberately treats a persisted `EXECUTING` state as requiring reconciliation rather than automatic replay because durable session state does not prove whether an external execution was already committed.
- M37 stores lease metadata and identifiers only; executable code is not persisted by the lease service.
- M38 performs local evidence reconciliation only.
- M39 makes remote reconciliation an explicit capability rather than an implicit side effect; no authoritative remote result is accepted without matching the original `execution_id`.
- M40 does not bypass human gates and never converts uncertain execution evidence into automatic replay.
- M41 persists only recovery metadata; it does not persist executable code, credentials, or idempotency keys.
- M42 adds no new execution authority; it only centralizes access to already-controlled recovery operations.
- M43 treats the Colab authority as read-only during reconciliation; no request is allowed to trigger fresh code execution.
- M44 makes durable session storage an explicit runtime configuration decision rather than an accidental side effect of the process lifecycle.
- M45 does not grant the Chainlit UI direct execution authority; recovery actions are authenticated, ownership-checked, and delegated to the runtime coordinator.
- M46 aggregates durable execution evidence only; batch reconciliation never submits execution and never authorizes retry.

## Repository readiness

M00–M45 are implemented with automated CI coverage. M46 is the active integration candidate in PR #63 and remains blocked from merge until a fresh CI result is available. The next logical work after M46 is broader protocol completion, observability, policy enforcement, durable distributed coordination, and integration hardening around worker/tool/QA lifecycles.

Environment-specific live validation remains intentionally deferred until a reachable runtime endpoint and required credentials are available.
