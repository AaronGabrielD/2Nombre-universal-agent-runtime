# M29 — Live cloud validation harness

M29 adds `scripts/m29_cloud_smoke.py`, a dependency-free validation client for a deployed Runtime/Colab execution service.

## Checks

The harness verifies:

1. unauthenticated health is reachable;
2. authenticated execution succeeds with a deterministic marker;
3. unauthenticated execution is rejected with HTTP 401.

It never prints the execution token.

## Usage

Set:

```text
UAR_SMOKE_BASE_URL=https://<reachable-runtime-service>
RUNTIME_EXECUTION_TOKEN=<token>
```

Then run:

```bash
python scripts/m29_cloud_smoke.py
```

The endpoint must expose the M12 `/health` and authenticated `/execute` contracts.

## Validation boundary

M29 is intentionally an executable harness, not a fabricated claim that external cloud services were reachable from this repository session. The repository's CI validates the harness itself; a real Colab/host deployment must run the script against its actual URL and token.
