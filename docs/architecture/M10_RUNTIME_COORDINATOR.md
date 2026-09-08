# M10 — Runtime Coordinator

## Purpose

M10 adds the first top-level coordination layer for a single runtime run. It connects M01 Session Manager, M02 Universal Intake, M04 Universal Architect, M05 Human Approval Engine, and M09 Supervisor/QA without moving their responsibilities into one monolithic service.

## Lifecycle covered

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
  ├─ MODIFY → REVISION
  └─ REJECT → REJECTED
```

## Security invariants

1. Building an architecture plan never authorizes execution by itself.
2. Gate A must be resolved by the approval engine before its decision can affect the run.
3. Approval decisions are verified against the original gate, including `run_id` ownership.
4. Supervisor `PASS` only opens Gate D; it never completes a run.
5. Only a recorded human `APPROVE` on Gate D permits `COMPLETED`.
6. The coordinator never executes code, invokes tools, selects execution backends, or contains UI logic.

## Why this layer exists

Before M10, the repository had strong module boundaries but no single service responsible for connecting them safely. The coordinator provides that seam for future presentation layers such as Chainlit, HTTP APIs, and CLI clients.

## Explicitly deferred

- Worker code generation and worker runtime execution.
- Tool authorization/execution integration with M07/M08.
- The actual Colab-side `/execute` service.
- Persistence beyond the existing session repository.
- UI/presentation code.
