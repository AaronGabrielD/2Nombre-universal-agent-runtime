# M31 — Contract Audit

M31 hardens the provider-neutral contracts at the runtime boundary.

## Scope

The core contracts now validate types and structural invariants before downstream modules consume them. Validation is explicit and raises `ContractValidationError` rather than leaking Python attribute/type errors.

Covered contracts:

- `WorkerSpec`
- `ArchitecturePlan`
- `TaskSpec`
- `ToolSpec`
- `ExecutionRequest`
- `ArtifactRef`
- `ExecutionResult`
- `HumanDecision`
- `FinalResult`

## Rules added

- identifiers and required textual fields must be non-empty strings
- string collections must contain non-empty strings
- architecture workers must be `WorkerSpec` instances
- worker limits must be positive integers
- tool schemas must be mappings
- booleans cannot be substituted with arbitrary truthy values
- execution timeouts must be real integers within bounds
- environment values must be strings
- execution duration cannot be negative
- artifacts must be valid `ArtifactRef` instances
- decision enum values must be valid
- final-result deliverables/tests must be structured object mappings

The changes preserve the existing provider-neutral API and are intentionally independent of Chainlit, CrewAI, Gemini, and execution backends.
