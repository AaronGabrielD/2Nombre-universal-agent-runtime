# M18 — Controlled Parallel Workers

## Purpose

M18 adds bounded concurrency for workers that already belong to the same M06 dependency-safe dispatch batch.

It does not change the dependency planner and does not create a second execution boundary.

## Safety invariants

- M06 remains responsible for dependency ordering. Only workers in the same ready batch may overlap.
- M13 validates the complete batch before starting worker threads.
- Duplicate tasks for the same worker are rejected before execution.
- Every task independently crosses M08 `ExecutionGateway`.
- M08 authorization remains mandatory; parallelism never bypasses Gate A or later authorization gates.
- M01 `SessionManager` is concurrency-safe, so result persistence from worker threads is serialized safely.
- Concurrency is bounded by `MAX_WORKERS` and the number of tasks in the batch.
- Results are returned in the original task order even when backend completion order differs.
- Sequential execution remains the default API behavior unless `parallel=True` is requested.

## Orchestrator behavior

M15 now builds the execution plans for all workers in a dependency-safe batch, then submits the resulting executable tasks to M13 as one batch. Batches containing multiple independent tasks use controlled parallel execution; a single-task batch remains effectively sequential.

CrewAI plan generation remains outside the concurrent execution pool. This keeps LLM planning isolated from execution scheduling while preserving the current worker/provider boundary.

## Failure semantics

A runtime or gateway exception while executing a batch is converted into worker error evidence for the affected orchestration pass. Results that the gateway successfully returns are persisted by M13 before being exposed to M15. QA in M09 still decides whether the run proceeds to Gate D or enters revision.

## Tests

`tests/test_worker_runtime.py` covers overlap of independent tasks, deterministic result ordering, preflight rejection of duplicate worker tasks, denied authorization, and evidence persistence.

The repository connector in this environment is used for source control operations, not as a Python execution environment. Therefore these tests are authored and structurally reviewed here but are not represented as locally executed results unless a CI runner reports them.