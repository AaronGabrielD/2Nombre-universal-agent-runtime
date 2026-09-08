# M15 — Integrated Orchestrator

## Purpose

M15 is the first end-to-end orchestration layer after human Gate A approval. It connects the existing contracts without replacing them.

## Flow

```text
Gate A APPROVE
      ↓
M06 WorkerFactory
      ↓
M06 Dispatcher
      ↓
M14 CrewAI Worker Adapter
      ↓
M13 Worker Runtime Adapter
      ↓
M08 Execution Gateway
      ↓
M01 Session Manager
      ↓
M09 Supervisor / QA
      ↓
Gate D
```

## Responsibilities

- create run-scoped workers from `ArchitecturePlan`;
- generate deterministic task contracts from worker missions;
- follow M06 dependency batches;
- obtain provider-generated execution plans through M14;
- route generated code exclusively through M13/M08;
- store worker and execution evidence in M01;
- invoke deterministic M09 QA;
- open Gate D only after QA PASS;
- route non-PASS outcomes to `REVISION`.

## Deliberate limitation

The first implementation processes workers sequentially inside each dependency batch. M06 still exposes dependency-safe batches, so controlled parallel execution can be introduced later without changing worker, tool, or backend contracts. This avoids unsafe concurrent mutation of the current in-memory session repository.

## Security invariants

1. `execute_run()` requires `EXECUTING` state.
2. `EXECUTING` is reachable through the recorded Gate-A approval path.
3. CrewAI output is untrusted data and is validated before execution.
4. Generated code cannot bypass M13/M08.
5. M08 remains the execution authorization boundary.
6. A QA PASS opens Gate D; it never completes the run.
7. Only human approval through M10 can reach `COMPLETED`.

## Provider strategy

CrewAI is optional and replaceable. The runtime can later add another worker provider with the same `WorkerExecutionPlan` contract.
