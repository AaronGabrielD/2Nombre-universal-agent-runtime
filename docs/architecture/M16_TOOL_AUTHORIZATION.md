# M16 — Tool Authorization & Gate C

M16 adds the policy bridge between M07 tool metadata, M05 human approval, and M08 execution authorization.

## Flow

```text
Worker required_tools / capabilities
          ↓
      M07 Registry
          ↓
   ToolAuthorizationService
       ↙          ↘
   safe tool      risky tool
      ↓              ↓
M08 authorization  Gate C (M05)
                       ↓
                 APPROVE / REJECT
                       ↓
                  M08 authorization
```

## Invariants

1. Unknown or unavailable tools fail closed.
2. High-risk or explicitly approval-required tools open Gate C.
3. Gate C rejection produces denied execution authorization.
4. Tool handlers are never called by this policy layer.
5. `run_id` ownership is checked before a Gate C decision is accepted.
6. M08 remains responsible for actual execution.
