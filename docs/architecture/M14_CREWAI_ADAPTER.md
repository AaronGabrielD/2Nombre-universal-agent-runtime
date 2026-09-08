# M14 — CrewAI Worker Adapter

## Purpose

M14 integrates CrewAI as an optional worker-orchestration provider without changing the runtime's contracts or approval hierarchy.

## Boundary

```text
M04 ArchitecturePlan
    -> M06 WorkerFactory / Dispatcher
        -> M14 CrewAI Worker Adapter
            -> WorkerExecutionPlan
                -> M13 WorkerRuntimeAdapter
                    -> M08 ExecutionGateway
```

CrewAI generates an execution plan for an already-authorized worker task. It does not execute the generated code, resolve approval gates, access the session repository directly, or select execution backends.

## Provider isolation

The adapter imports CrewAI lazily. The core runtime can therefore be installed without the optional dependency. Install `requirements-crewai.txt` only when CrewAI-backed workers are enabled.

The current implementation uses CrewAI's `Agent`, `Task`, `Crew`, `Process`, and `LLM` APIs with a single sequential task per worker. M06 remains responsible for inter-worker dependency ordering and future parallelism.

CrewAI 1.15.20 was pinned because it is the latest stable release identified during implementation. PyPI lists Python >=3.10 and <3.14 for this release.

## Output contract

CrewAI must return one JSON object containing:

- `summary`
- `language`
- `code`
- `timeout_seconds`
- `needs_network`
- `environment`

The adapter validates all fields before constructing `WorkerExecutionTask`.

## Security invariants

1. CrewAI output is treated as untrusted generated data.
2. Generated code never executes inside the CrewAI adapter.
3. Execution still requires the explicit `ExecutionAuthorization` path in M08.
4. Worker/run identity is validated by M13.
5. Tool use is not exposed to the CrewAI agent by default.
6. CrewAI remains replaceable; no core contract depends on CrewAI classes.
