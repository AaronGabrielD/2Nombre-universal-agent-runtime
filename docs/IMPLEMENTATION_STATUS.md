# Implementation status

M00–M41 are implemented in `main` with automated CI coverage. Environment-specific live validation that requires external endpoints or credentials remains intentionally deferred.

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
  -> explicit RecoveryResumeService action
  -> no automatic execution/replay

Execution replay protection:
  -> ExecutionLeaseService
  -> deterministic idempotency key
  -> RUNNING lease blocks duplicate replay
  -> COMPLETED lease reuses persisted execution result

Execution reconciliation:
  -> ExecutionReconciliationService
  -> local durable evidence inspection
  -> explicit backend authority when configured
  -> authoritative result persisted locally
  -> no implicit remote calls or retry

Colab authoritative reconciliation:
  -> AuthoritativeColabHTTPServer
  -> durable execution-evidence/<execution_id>.json
  -> authenticated GET /executions/<execution_id>
  -> ColabExecutionReconciler
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
- M15 — Integrated Runtime Orchestration
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
- M27 — Stronger Docker Execution Isolation
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
- M41 — Authoritative Colab execution reconciliation
- M42 — Failed execution recovery routing hardening

## Revision and recovery hardening

M32 adds explicit revision records and durable history. M33 routes recoverable Supervisor QA revisions and Gate C denials through `RuntimeCoordinator` and `RevisionService`, returning the run to `ARCHITECTING` instead of mutating `REVISION` directly. M34 adds a per-service configurable revision ceiling (default 3) and rejects additional revision requests before mutating workflow state. M35 adds repository-wide session enumeration and `SessionManager.list_recoverable_sessions()` so a new process can discover non-terminal runs from SQLite, JSON, or in-memory storage without automatically executing anything. M36 adds explicit recovery checkpoints that classify persisted state and evidence without replaying worker execution or bypassing human gates.

M37 adds a durable execution lease for every worker task. A deterministic idempotency key identifies the same run/worker/task/code combination. An active lease blocks a second execution attempt, while a completed lease reuses the persisted execution result instead of invoking the backend again.

M38 adds an execution reconciliation layer that correlates a durable lease with persisted `ExecutionResult` evidence. A task is only locally classified as completed or failed when a matching durable result exists. An active lease without a result becomes `PENDING_BACKEND_CHECK`; the runtime does not silently retry it.

M39 adds an explicit provider-neutral `ExecutionReconciler` contract. `ExecutionReconciliationService.reconcile_backend()` may query a configured backend authority only when called explicitly, rejects inconsistent execution identifiers, persists returned authoritative evidence, and refuses retry when the backend is unavailable or cannot produce a result.

M40 adds `RecoveryResumeService`, which makes post-restart recovery executable only through an explicit `RecoveryAction`. Architecture rebuilds may return `REVISION` to `ARCHITECTING`; supervision can only resume from `SUPERVISING`; execution recovery requires an idempotency key and first reconciles durable evidence before optionally consulting an explicitly configured backend authority. Ambiguous or terminal recovery actions are rejected.

M41 adds a concrete Colab implementation of the M39 authority boundary. An authoritative server variant durably records terminal execution evidence as explicit JSON and exposes it through an authenticated `GET /executions/<execution_id>` endpoint. The client `ColabExecutionReconciler` performs read-only evidence lookup and never executes code. Missing evidence remains non-authoritative.

M42 hardens the failed-execution recovery path. An authoritative execution failure is routed through the legal `EXECUTING → SUPERVISING → REVISION → ARCHITECTING` sequence using `RevisionService`; the recovery layer no longer attempts an illegal direct `EXECUTING → REVISION` transition.

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
- M41 stores execution evidence explicitly and durably on the remote runtime; it does not store executable source code in the evidence record.
- M42 preserves the existing state machine and routes failure recovery through the established revision service.

## Repository readiness

M00–M41 are implemented with automated CI coverage. M42 is the active development milestone. Remaining work is concrete authoritative adapters for other backends, stronger coordinator/recovery integration, richer worker/tool/QA protocols, complete UI/API surfaces, observability, stronger policy enforcement, durable distributed coordination, and broader integration testing.

Environment-specific live validation remains intentionally deferred until a reachable runtime endpoint and required credentials are available.
