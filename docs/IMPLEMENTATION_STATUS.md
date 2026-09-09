# Implementation status

M00–M32 are implemented in `main` with automated CI coverage. Environment-specific live validation that requires external endpoints or credentials remains intentionally deferred.

Current integrated path:

```text
User / Chainlit
  -> Auth + Run Authorization
  -> Intake
  -> Architect
  -> Gate A (Human)
  -> Worker Factory / Dispatcher
  -> CrewAI Worker Adapter
  -> Tool Authorization
      -> Gate C (Human) when required
  -> Execution Gateway
      -> Docker backend (local hardened option)
      -> Colab HTTP backend (remote option)
  -> Supervisor / QA
  -> Gate D (Human)
  -> Completed | Revision | Rejected

Revision path:
  -> RevisionService (reason/source/feedback/attempt)
  -> ARCHITECTING
  -> new architecture approval cycle
```

## Milestones

- M00 — Foundation & Contracts
- M01 — Session Manager
- M02 — Universal Intake
- M03 — Gemini Adapter
- M04 — Universal Architect
- M05 — Human Approval Engine
- M06 — Worker Factory & Dispatcher
- M07 — Tool Registry & Capability Registry
- M08 — Execution Gateway
- M09 — Supervisor & QA
- M10 — Runtime Coordinator
- M11 — Chainlit Presentation
- M12 — Colab Execution Service
- M13 — Worker Runtime Adapter
- M14 — CrewAI Worker Adapter
- M15 — Integrated Orchestrator
- M16 — Tool Authorization + Gate C
- M17 — Session Concurrency
- M18 — Controlled Parallel Workers
- M19 — Tool Registry orchestration + Gate C pause/resume
- M20 — HTTP integration tests
- M21 — Persistent session storage
- M22 — Chainlit auth hardening
- M23 — execution policy
- M24 — CI
- M25 — provider-neutral deployment adapter
- M26 — multi-user durable identity/authorization
- M27 — Stronger Docker execution isolation backend
- M28 — Schema-versioned persistence migrations + JSON durable session backend
- M29 — Live cloud smoke-validation harness
- M30 — Integrated runtime composition + Chainlit orchestration
- M31 — Hardened provider-neutral core contracts
- M32 — Revision tracking + recovery loop

## Revision and recovery hardening

M32 adds an explicit revision record and recovery service. Human architecture or final-result modification requests are recorded with an immutable revision ID, source, feedback and attempt number before returning the run to `ARCHITECTING`. Revision history is reconstructed from persisted session messages so a new service instance can recover it without in-memory state.

## Security and deployment boundaries

- M27 provides container-level defense in depth when Docker is available; it is not a high-assurance VM boundary.
- M23 execution policy is defense in depth, not a sandbox.
- M22 authentication and M26 run authorization are application-layer controls.
- M25 remains provider-neutral deployment rendering; it does not provision third-party infrastructure automatically.
- Direct tool handlers remain declarative and execution stays behind M08.

## Repository readiness

M00–M32 are implemented with automated CI coverage. Remaining work is post-blueprint hardening and productization: orchestration-wide revision integration, revision limits, richer worker/tool/QA protocols, complete UI/API surfaces, observability, stronger policy enforcement, durable distributed coordination, and broader integration testing.

Environment-specific live validation remains intentionally deferred until a reachable runtime endpoint and required credentials are available.