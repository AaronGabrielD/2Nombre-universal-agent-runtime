# M00 — Foundation & Contracts

## Purpose

M00 defines the provider-neutral vocabulary and safety boundaries used by every later module.
It does not import Chainlit, CrewAI, Gemini, Colab or a hosting provider.

## Deliverables

- `app/core/config.py` — environment-backed settings.
- `app/core/states.py` — workflow state machine and legal transitions.
- `app/core/models.py` — mutable run context and structured events.
- `app/core/contracts.py` — stable DTO/domain contracts.
- `app/core/exceptions.py` — domain errors.
- `app/core/logging.py` — structured operational logs.
- `tests/test_core.py` — initial contract/state regression tests.

## Boundary rules

1. Core must remain provider-neutral.
2. Core must not depend on Chainlit UI primitives.
3. Core must not call an LLM.
4. Core must not execute arbitrary code.
5. Secrets are loaded from environment variables and never serialized into logs.
6. Every run receives a unique `run_id`.
7. Illegal workflow transitions are rejected.
8. High-risk tools cannot exist without human approval enabled.

## Integration points

Later modules consume these contracts:

- M01 Session Manager → `RunContext`, `WorkflowState`, `EventRecord`.
- M02 Intake → `ArtifactRef` and run context.
- M03 Gemini → configuration + architect/worker/supervisor model names.
- M04 Architect → `ArchitecturePlan`, `WorkerSpec`, `TaskSpec`.
- M05 Human → `HumanDecision`.
- M06 Dispatcher → `WorkerSpec`.
- M07 Tools → `ToolSpec`.
- M08 Execution Gateway → `ExecutionRequest` / `ExecutionResult`.
- M09 Supervisor → `FinalResult`, execution results and events.

## Completion criteria

M00 is complete when all unit tests pass and no core module imports provider-specific packages.
