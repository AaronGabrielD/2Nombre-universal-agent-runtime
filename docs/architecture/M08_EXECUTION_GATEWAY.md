# M08 — Execution Gateway

## Purpose

M08 is the single execution boundary between the orchestration layer and any runtime backend. It accepts validated `ExecutionRequest` contracts, requires explicit authorization, selects an available backend, and delegates execution.

## Backend neutrality

The gateway depends only on the `ExecutionBackend` contract. A backend can later be implemented for Google Colab, a local process, Docker, or a remote worker service without changing M08's public contract.

```text
Workers / Supervisor
        |
        | ExecutionRequest + authorization
        v
+-----------------------+
|          M08          |
|   Execution Gateway   |
+-----------------------+
        |
        | backend contract
        v
+-----------------------+
| Colab / Docker / etc. |
+-----------------------+
```

## Safety rules

1. Execution is denied by default when no explicit authorization is supplied.
2. A denied request never reaches a backend.
3. Unregistered or unavailable backends fail closed with `UNAVAILABLE`.
4. Backend timeouts and exceptions are normalized to stable execution statuses.
5. A backend must return the same `execution_id` it received; inconsistent results are rejected.
6. M08 does not decide whether a human should approve an action. Upstream approval/policy layers make that decision and provide an `ExecutionAuthorization` record.

## Separation from M07

M07 answers: “Which tools/capabilities exist and are available?”

M08 answers: “Where can this execution run, and may it be delegated now?”

Actual tool discovery remains in M07; actual backend execution occurs only after M08 authorization checks.

## Initial scope

M08 intentionally does not ship a real Colab client yet. The contract is ready for a backend adapter in the next integration step, while tests use an in-memory fake backend to verify gateway behavior without executing arbitrary code.
