# Implementation status

M00–M47 internal hardening and deployment preflight are integrated on `main`. The repository remains in M47 operational/E2E validation; external-provider validation and public deployment are still separate live-validation work.

Recent corrective hardening included:

- Production container now sets `PYTHONPATH=/app`, includes Docker CLI only, and exposes an HTTP healthcheck.
- Docker backend now passes a valid executable search PATH to its bounded subprocess runner.
- CrewAI remains optional; when unavailable, runtime composition falls back to the native Gemini worker adapter.
- Architect prompts now receive the configured worker limit explicitly before generation.
- CI now builds, starts, and health-checks the production container rather than only checking the CLI binary.
- Accidental placeholder content was removed from the repository root.

The Chainlit security follow-up remains tracked separately in issue #79.
