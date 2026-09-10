# M11 — Chainlit Presentation

## Scope

M11 is the human-facing presentation adapter for the runtime. It uses Chainlit as the UI layer while keeping orchestration, authorization, execution, persistence, and recovery behind the application's canonical runtime services.

## Responsibilities

- Start a runtime run from a user message.
- Forward attached files to M02.
- Display the generated architecture plan.
- Present Gate A as explicit UI actions.
- Capture human modification, clarification, and approval text.
- Surface worker progress and human-input requests without exposing private chain-of-thought.
- Surface Gate C decisions for risky tool actions.
- Surface Gate D and final results.
- Discover authenticated recoverable runs and expose explicit recovery actions.
- Delegate all state changes to `RuntimeCoordinator` and the existing approval/recovery boundaries.

## Non-responsibilities

The Chainlit layer does not:

- execute code;
- call execution backends directly;
- authorize tool or code execution;
- mutate `RunContext` directly;
- decide whether supervisor QA passes;
- bypass M05 approval gates;
- perform automatic restart replay.

## Current UI lifecycle

```text
Chainlit message
  -> Runtime composition root
  -> M10 RuntimeCoordinator
  -> M02 Intake
  -> M04 Architect
  -> Gate A UI / M05 Approval
  -> Worker Factory / Dispatcher
  -> Worker + Tool Authorization
  -> Gate C UI when required
  -> Execution Gateway
  -> Supervisor / QA
  -> Gate D UI
  -> Completed | Revision | Rejected
```

## Recovery lifecycle

```text
Authenticated user
  -> recoverable-run discovery
  -> Recovery inspection
  -> explicit RecoveryAction
  -> M42 RuntimeCoordinator recovery facade
  -> reconciliation or revision routing
  -> durable recovery audit
```

An `EXECUTING` recovery requires the original idempotency key and never implies that code should be re-executed automatically. Human-gated states remain paused until the corresponding decision is supplied.

## File uploads

Chainlit's spontaneous file upload feature is enabled with a 50 MB UI limit in `config.toml`. M02 remains authoritative for its own configured upload limits and ingestion strategy; the UI limit is not a substitute for backend validation.

## HTML safety

`unsafe_allow_html` remains disabled in the current configuration. HTML preview must remain a deliberately sandboxed presentation capability and must not become an implicit execution privilege.

## Authentication

Authentication and run ownership are enforced at the application boundary. The recovery surface is authenticated and ownership-checked before recoverable sessions are exposed or recovery actions are delegated.

## Architecture boundary

M11 is a presentation adapter, not a second composition root. Runtime services are constructed through `app.runtime.bootstrap.build_runtime()` so Chainlit does not create independent session, authorization, execution, or persistence stacks.

## Historical note

Earlier M11 documentation described only the pre-integration lifecycle through Gate A. M30 and later milestones completed the runtime composition, worker/execution/supervisor path, Gate C handling, Gate D flow, and authenticated recovery surface. The lifecycle above is authoritative for current `main`.

## Local launch

```bash
pip install -r requirements.txt
chainlit run app/ui/chainlit_app.py
```
