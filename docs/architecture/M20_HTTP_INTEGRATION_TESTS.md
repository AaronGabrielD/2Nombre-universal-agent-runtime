# M20 — HTTP Integration Tests

## Purpose

M20 validates the real HTTP boundary between the M08 Colab execution client and the M12 Colab execution service without requiring a live Colab runtime.

## Scope

- Start an in-process HTTP service double using the standard-library server.
- Exercise the actual M08 `ColabExecutionBackend` request/response path.
- Verify bearer-token authentication.
- Verify execution-id correlation and response normalization.
- Verify service-side rejection of malformed or unauthorized requests.
- Keep generated worker code out of the test process; the HTTP double returns deterministic execution evidence.

## Next implementation constraint

The production Colab service remains the execution boundary. These tests are not a substitute for live cloud validation; they prove that the two runtime halves agree on their HTTP contract.
