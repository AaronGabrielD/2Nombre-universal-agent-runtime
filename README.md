# Universal Agent Runtime

Universal multi-agent runtime under active construction.

## Progress

- **M00 — Foundation & Contracts:** ✅
- **M01 — Session Manager:** ✅
- **M02 — Universal Intake:** ✅
- **M03 — Gemini Adapter:** ✅
- **M04 — Universal Architect:** ✅
- **M05 — Human Approval Engine:** ✅
- **M06 — Worker Factory & Dispatcher:** ✅
- **M07 — Tool Registry & Capability Registry:** ✅
- **M08 — Execution Gateway:** ✅
- **M09 — Supervisor & QA:** ✅
- **M10 — Runtime Coordinator:** ✅
- **M11 — Chainlit Presentation:** ✅
- **M12 — Colab Execution Service:** ✅
- **M13 — Worker Runtime Adapter:** ✅
- **M14 — CrewAI Worker Adapter:** ✅

## Architecture

See `BLUEPRINT_MASTER_v1.md` for the master architecture and `docs/architecture/` for milestone boundaries.

## Runtime coordination

M10 connects the existing lifecycle services while preserving their boundaries. It enforces the human approval checkpoints required before execution and completion.

See `docs/architecture/M10_RUNTIME_COORDINATOR.md`.

## Presentation

M11 adds the first Chainlit interface for intake, architecture display, and human Gate A interaction. It deliberately does not execute workers or tools from the UI layer.

See `docs/architecture/M11_CHAINLIT_PRESENTATION.md`.

## CrewAI integration

M14 adds an optional CrewAI adapter. CrewAI generates worker execution plans, but M13/M08 remain the exclusive execution path and M05 remains authoritative for human approval.

Install the optional integration with:

```bash
pip install -r requirements-crewai.txt
```

See `docs/architecture/M14_CREWAI_ADAPTER.md`.

## Security rule

Never commit `.env`, API keys, tokens, credentials, or local runtime artifacts.
