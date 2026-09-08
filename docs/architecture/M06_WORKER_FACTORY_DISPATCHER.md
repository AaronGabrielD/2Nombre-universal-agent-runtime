# M06 — Worker Factory & Dispatcher

## Responsibility

M06 converts an approved `ArchitecturePlan` into run-scoped `WorkerInstance` objects and computes dependency-safe dispatch batches. It does not execute workers, invoke tools, call the LLM, or access Colab.

## Boundary

```text
ArchitecturePlan
      ↓
 WorkerFactory
      ↓
WorkerInstance[]
      ↓
WorkerDispatcher
      ↓
DispatchBatch[] ──→ execution/orchestration layer
```

## Factory

`WorkerFactory` validates the architecture against the configured worker ceiling and binds each worker to exactly one `run_id`. This prevents accidental cross-run worker reuse.

## Dispatcher

The dispatcher builds a directed dependency graph from `WorkerInstance.dependencies` and performs a topological scheduling pass. Workers with no unresolved dependencies are placed in the same `DispatchBatch`, allowing later orchestration code to execute them concurrently.

A worker becomes eligible only after every declared dependency has been dispatched in a previous batch. Cycles and unresolved dependencies fail closed with `WorkerDispatchError`.

## Tasks

`WorkerDispatcher.build_task()` creates a validated M00 `TaskSpec`. Dispatch only validates task ownership and groups tasks with their worker; it never executes task code.

## Concurrency and safety

The dispatcher is deterministic for equal inputs: worker IDs and newly-ready IDs are sorted before batches are emitted. The module therefore provides a stable execution plan while leaving actual concurrency to the execution/orchestration layer.

## Integration boundary

M07 will determine which declared tools/capabilities are actually available. M08 will execute approved work through the execution gateway. M06 must remain ignorant of those backend details.

## Testing

`tests/test_workers.py` covers run scoping, parallel independent workers, dependency ordering, cycle detection, cross-run protection, unknown task workers and the worker safety ceiling.
