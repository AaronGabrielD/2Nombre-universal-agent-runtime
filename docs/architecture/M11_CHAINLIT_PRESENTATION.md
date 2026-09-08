# M11 — Chainlit Presentation

## Scope

M11 adds the first human-facing presentation adapter. It uses Chainlit 2.12.0, the current PyPI release at the time of implementation. Chainlit provides lifecycle hooks, clickable Actions, user-session state, and spontaneous file uploads.

## Responsibilities

- Start a runtime run from a user message.
- Forward attached files to M02.
- Display the generated architecture plan.
- Present Gate A as explicit UI actions.
- Capture human modification/clarification text.
- Forward gate decisions to M05 through M10.
- Show terminal state without claiming work that has not happened.

## Non-responsibilities

The Chainlit layer does not:

- execute code;
- call tools directly;
- authorize executions;
- mutate `RunContext` directly;
- decide whether supervisor QA passes;
- bypass M05 approval gates.

## Current UI lifecycle

```text
Chainlit message
  -> M10.start_run
  -> M10.build_architecture
  -> Gate A UI
  -> M05.resolve_gate
  -> M10.apply_architecture_decision
  -> EXECUTING
```

The later execution/worker/supervisor stages remain intentionally incomplete until their runtime integration is added.

## File uploads

Chainlit's spontaneous file upload feature is enabled with a 50 MB UI limit in `config.toml`. M02 remains authoritative for its own configured upload limits and ingestion strategy; the UI limit is not a substitute for backend validation. Chainlit exposes uploaded message elements to `on_message`.

## HTML safety

`unsafe_allow_html` is disabled in the current configuration. HTML preview must remain a later, explicitly sandboxed capability rather than an implicit UI privilege.

## Authentication

Chainlit applications are public by default unless authentication is configured. The current PoC does not invent or commit credentials. A production/private deployment must configure `CHAINLIT_AUTH_SECRET` and an authentication callback before exposing the UI publicly.

## Local launch

```bash
pip install -r requirements.txt
chainlit run app/ui/chainlit_app.py
```

