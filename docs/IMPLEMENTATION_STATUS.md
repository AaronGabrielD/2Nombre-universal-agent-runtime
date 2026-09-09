# Implementation Status

This file tracks the implementation order as the repository evolves beyond the original Blueprint v1.0 numbering.

## Completed

- M00 — Foundation & Contracts
- M01 — Session Manager
- M02 — Universal Intake
- M03 — Gemini Adapter
- M04 — Universal Architect
- M05 — Human Approval Engine
- M06 — Worker Factory & Dispatcher
- M07 — Tool Registry & Capability Registry
- M08 — Execution Gateway + Colab HTTP client adapter
- M09 — Supervisor & QA
- M10 — Runtime Coordinator
- M11 — Chainlit Presentation
- M12 — Colab Execution Service
- M13 — Worker Runtime Adapter
- M14 — CrewAI Worker Adapter
- M15 — Integrated Orchestrator
- M16 — Tool Authorization + Gate C service
- M17 — Session Concurrency Hardening
- M18 — Controlled Parallel Worker Execution
- M19 — Tool Registry orchestration + Gate C pause/resume
- M20 — HTTP integration test coverage (M08 ↔ M12)
- M21 — Persistent session storage via SQLite repository
- M22 — Chainlit authentication hardening
- M23 — Static Python execution admission policy
- M24 — Automated CI validation
- M25 — Provider-neutral deployment adapter
- M26 — Multi-user durable identity and run authorization

## Current integrated path

```text
User / Chainlit
  -> M22/M26 Authenticated UI + Durable Identity
  -> M26 Run Ownership Authorization
  -> M02 Intake
  -> M04 Architect
  -> Gate A (M05)
  -> M06 Worker Factory + Dependency Batches
  -> M07 Tool Registry + M16 Tool Authorization
  -> Gate C when required
  -> M14 CrewAI Worker Adapter
  -> M13 Worker Runtime Adapter
  -> M08 Execution Gateway
  -> M12 Colab Execution Service
  -> M23 Python Execution Admission Policy
  -> M01 Session evidence
  -> M21 Persistent Session Repository (optional)
  -> M09 Supervisor / QA
  -> Gate D (M05/M10)
  -> Completed | Revision | Rejected

Cross-cutting controls:
  M17 Concurrent Session Writes
  M18 Bounded Parallel Execution
  M20 HTTP Contract Integration Tests
  M24 Automated CI Test Suite
  M25 Provider-Neutral Deployment Boundary
  M26 Durable Identity + Owner/Administrator Run Access
```

## M26 scope

M26 adds a provider-neutral identity layer backed by SQLite without storing plaintext passwords. Users have a stable `user_id`, username, PBKDF2 password record, enabled state, and role (`user` or `admin`). The environment-backed account from M22 remains a bootstrap mechanism: the first successful login persists that identity into the configured SQLite database without overwriting an existing record.

Runtime sessions created through Chainlit receive immutable owner metadata. Normal users may access only their own runs; administrators may access runs across users. Gate actions are checked against the same ownership boundary before any decision is applied.

## Intentionally not complete yet

- Strong OS/container isolation beyond static admission controls and the Colab VM boundary.
- Provider-neutral durable storage backends beyond SQLite and schema-versioned migrations.
- Deployment execution against a concrete hosting provider; M25 currently validates and renders deployment plans without performing external provisioning.
- Full live Colab + Chainlit + Gemini end-to-end validation in a real cloud runtime.
- Direct tool-handler execution from workers; tools remain declarative and execution stays behind M08.

## Next engineering priority

1. M27 — Stronger OS/container execution isolation where available.
2. M28 — Schema-versioned persistence migrations and durable backends.
3. M29 — Live cloud validation against the real Google Colab service and configured Gemini provider.
