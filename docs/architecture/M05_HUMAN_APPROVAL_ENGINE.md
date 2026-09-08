# M05 — Human Approval Engine

## Responsibility

M05 owns the runtime's human approval gates. It pauses a workflow by creating an open `ApprovalGate`, exposes that gate to an external UI or adapter, validates the human response, and records the resulting `HumanDecision`.

## Boundary

```text
orchestrator → HumanApprovalEngine → ApprovalGate
                                  ↑
                       Chainlit / API / CLI adapter
                                  ↓
                              HumanDecision
```

M05 has no dependency on Chainlit, CrewAI, Gemini, or an execution backend. This keeps approval policy reusable across interfaces and deployment targets.

## Gate lifecycle

`OPEN → RESOLVED`

`OPEN → CANCELLED`

A resolved or cancelled gate cannot be resolved again. A duplicate or late response raises `ApprovalError` instead of silently overwriting state.

## Decisions

The engine reuses the M00 `HumanDecisionType` contract:

- `APPROVE` — continue with the proposed action.
- `MODIFY` — continue only after an upstream module incorporates the feedback.
- `REJECT` — stop or route to a rejection/replanning path.
- `CLARIFY` — request clarification before proceeding.

M05 records the decision but does not decide what the next workflow state should be. That belongs to the orchestration/state-machine layer.

## Audit behavior

Every successful resolution appends an immutable decision record. Read APIs return snapshots/history and never expose mutable internal gate state.

The engine uses a lock around lifecycle mutations so duplicate concurrent responses cannot both resolve the same gate.

## Security boundary

The UI must never be treated as an authority beyond submitting a validated `HumanDecision`. High-risk execution approval remains a policy concern of the orchestration/tool layer; M05 only provides the approval primitive.

## Testing

`tests/test_approval.py` covers creation, filtering by run, each decision type, disallowed decisions, duplicate/late responses, cancellation, immutable history and concurrent resolution.
