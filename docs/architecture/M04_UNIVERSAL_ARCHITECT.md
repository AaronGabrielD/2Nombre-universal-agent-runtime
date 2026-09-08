# M04 — Universal Architect

## Responsibility

M04 transforms a normalized user objective and intake context into a validated `ArchitecturePlan`.
It does not execute tools, create artifacts, or perform the requested work.

## Boundary

```text
ArchitectureInput → LLMProvider → JSON plan → ArchitecturePlan
```

The architect depends only on the provider-neutral `LLMProvider` contract from M03. Gemini is selected by configuration, so tests can inject a fake provider and the orchestration layer remains vendor-neutral.

## Output

The plan contains:

- objective and assumptions
- constraints and testable acceptance criteria
- risks and required capabilities
- dynamically selected workers, each with a mission, deliverables, tools and dependencies

Worker IDs are unique and dependencies are validated against workers in the same plan. The configured `MAX_WORKERS` safety ceiling is enforced by the M00 contract validation.

## Human authority

M04 never assumes approval. The next module, M05, owns the human approval gate for the proposed architecture.

## Reliability

The service accepts plain JSON and JSON fenced in Markdown. Malformed or contract-invalid responses raise `ArchitectPlanningError`; no partial plan is returned. Provider retries remain the responsibility of M03.

## Privacy and reasoning policy

The architect prompt requests operational planning data only. It explicitly forbids disclosure of private chain-of-thought. Logs and UI layers should expose status, decisions, tool calls and outputs rather than hidden reasoning.

## Testing

`tests/test_architect.py` uses an offline fake provider and covers valid plans, fenced JSON, malformed responses, invalid dependencies, worker-limit enforcement and early input validation.
