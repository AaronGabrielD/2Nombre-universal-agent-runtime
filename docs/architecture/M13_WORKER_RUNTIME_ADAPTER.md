# M13 — Worker Runtime Adapter

## Purpose

M13 creates the execution seam between M06's dependency-safe worker batches and M08's backend-neutral `ExecutionGateway`.

## Responsibilities

- accept a validated `DispatchBatch`;
- accept executable task descriptions supplied by an upstream worker implementation;
- validate that every task belongs to a worker in the batch;
- construct one `ExecutionRequest` per task;
- forward every request through M08;
- persist the resulting `ExecutionResult` in M01.

## Non-responsibilities

The adapter does not:

- generate worker code;
- decide human approval;
- call LLMs directly;
- call tool handlers directly;
- bypass M08;
- select workers outside the supplied dispatch batch.

## Authorization rule

`ExecutionAuthorization` is passed explicitly into every batch invocation. M08 remains authoritative: a denied authorization produces `DENIED` and the backend is not called. The adapter does not reinterpret approval policy.

## Isolation rule

Each `WorkerExecutionTask` must reference a worker in the exact `DispatchBatch`. The batch itself is run-scoped and all workers must have the same `run_id`. This prevents a task from one run from being executed under another run's identity.

## Planned next step

A future worker implementation adapter can generate or obtain `WorkerExecutionTask` objects from an LLM/orchestration framework such as CrewAI. That integration must remain behind this boundary so CrewAI does not replace the runtime's contracts or human approval hierarchy.
