# M10 — Runtime Coordinator

## Purpose

M10 is the canonical coordination boundary for a single runtime run. It connects the session manager, intake, architect, human approval engine, workers, tool authorization, execution gateway, supervisor/QA, and recovery services without moving those responsibilities into one monolithic service.

## Integrated lifecycle

```text
INTAKE
  ↓
ARCHITECTING
  ↓
WAITING_ARCHITECT_APPROVAL
  ├─ APPROVE → EXECUTING
  ├─ MODIFY / CLARIFY → ARCHITECTING
  └─ REJECT → REJECTED

EXECUTING
  ↓
SUPERVISING
  ↓
WAITING_FINAL_APPROVAL
  ├─ APPROVE → COMPLETED
  ├─ MODIFY → REVISION → ARCHITECTING
  └─ REJECT → REJECTED

RESTART RECOVERY
  ↓
Recovery inspection
  ↓
Explicit RecoveryAction
  ├─ resume supervision
  ├─ reconcile execution
  └─ create revision → ARCHITECTING
```

The coordinator exposes the canonical application boundary for Chainlit and other presentation/API layers. Runtime composition is built once and injected through `app.runtime.bootstrap.build_runtime()`.

## Security invariants

1. Building an architecture plan never authorizes execution by itself.
2. Gate A must be resolved by the approval engine before workers can start.
3. Approval decisions are verified against the original gate, including `run_id` ownership.
4. Supervisor `PASS` only opens Gate D; it never completes a run.
5. Only a recorded human `APPROVE` on Gate D permits `COMPLETED`.
6. Risky tool execution remains behind tool authorization and Gate C when required.
7. Recovery is explicit and fail-closed: persisted uncertain execution is reconciled rather than silently replayed.
8. The coordinator does not contain provider-specific LLM or backend execution logic.

## Recovery responsibilities

M42 extends M10 with the canonical recovery facade. `inspect_recovery()` classifies persisted recovery checkpoints without mutation; `resume_recovery()` accepts only an explicit `RecoveryAction`, delegates validation to the recovery service, and preserves durable audit and revision boundaries.

## Why this layer exists

M10 is the stable seam between domain services and presentation/API clients. The composition root can swap persistence and execution backends without changing orchestration callers, while run ownership and human-gate invariants remain centralized.

## Historical note

Earlier M10 documentation described a smaller lifecycle that ended at the first `EXECUTING` transition. That description is retained only in repository history. The integrated lifecycle above is authoritative for the current `main` branch.
