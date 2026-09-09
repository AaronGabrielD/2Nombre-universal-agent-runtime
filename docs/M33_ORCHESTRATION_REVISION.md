# M33 — Orchestration-wide revision integration

M33 makes recoverable revision requests uniform across the integrated orchestration path.

The orchestrator must never move a run directly to `REVISION` when the cause is recoverable. Instead it records a `RevisionRequest` through `RuntimeCoordinator`, preserving reason, source, feedback, attempt number, and durable session evidence before re-entering `ARCHITECTING`.

Covered sources:

- Supervisor QA that returns `REVISE`.
- Human rejection of a risky tool request at Gate C.
- Future recoverable orchestration failures should use the same boundary.

External cloud validation remains intentionally deferred.