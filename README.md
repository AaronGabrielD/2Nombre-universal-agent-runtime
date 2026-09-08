# Universal Agent Runtime

Universal multi-agent runtime under active construction.

## Current milestone

**M02 — Universal Intake**

Implemented milestones:

- **M00 — Foundation & Contracts:** provider-neutral contracts, configuration, workflow states, structured events, and regression tests.
- **M01 — Session Manager:** unique run lifecycle, isolated session state, lifecycle transitions, and repository boundary.
- **M02 — Universal Intake:** objective normalization, upload limits, file metadata registration, and provider-neutral ingestion strategy selection.

## Architecture

See `BLUEPRINT_MASTER_v1.md` for the master architecture and `docs/architecture/` for milestone boundaries.

## Security rule

Never commit `.env`, API keys, tokens, credentials, or local runtime artifacts.
