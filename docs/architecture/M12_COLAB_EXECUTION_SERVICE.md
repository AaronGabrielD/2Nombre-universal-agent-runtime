# M12 — Colab Execution Service

## Purpose

M12 implements the remote HTTP service that corresponds to the existing `ColabExecutionBackend` adapter in M08. The service is intended to run inside Google Colab and uses only the Python standard library.

## API

### `GET /health`

Returns a small status object and does not reveal configuration secrets.

### `POST /execute`

Requires:

```text
Authorization: Bearer <RUNTIME_EXECUTION_TOKEN>
Content-Type: application/json
```

The JSON request follows the M08 `ExecutionRequest` shape. The service currently executes Python only.

### `GET /artifacts/<execution_id>/<path>`

Requires the same bearer token. Stored artifacts are served only from the execution's artifact directory and path traversal is rejected.

## Execution controls

- no shell invocation (`shell=False`);
- Python runs in a temporary working directory;
- stdin is closed;
- execution timeout is configurable and bounded;
- stdout/stderr are capped before returning them;
- request body size is bounded;
- environment variables are reduced to a small base set and request variables with secret-like names are rejected;
- explicit network-required requests are denied by default;
- artifact count and artifact size are bounded;
- execution identifiers are validated before entering filesystem paths.

## Important security limitation

A Google Colab runtime is not a hardened sandbox. The service can reduce accidental exposure and enforce policy at the HTTP boundary, but `needs_network=false` does not technically disable networking inside Python. Do not treat this service as a hostile-code isolation boundary.

For stronger isolation, a future backend should use a real container/VM sandbox behind M08.

## Environment variables

Required:

```text
RUNTIME_EXECUTION_TOKEN
```

Optional defaults:

```text
RUNTIME_BIND_HOST=0.0.0.0
RUNTIME_PORT=8000
RUNTIME_ARTIFACT_ROOT=/content/universal-agent-runtime-artifacts
RUNTIME_MAX_REQUEST_BYTES=2097152
RUNTIME_MAX_OUTPUT_BYTES=262144
RUNTIME_MAX_ARTIFACT_BYTES=10485760
RUNTIME_MAX_ARTIFACTS=20
RUNTIME_DEFAULT_TIMEOUT_SECONDS=60
RUNTIME_MAX_TIMEOUT_SECONDS=600
RUNTIME_ALLOW_NETWORK=false
RUNTIME_PUBLIC_BASE_URL=
```

`RUNTIME_PUBLIC_BASE_URL` is optional. When present, artifact references are generated as HTTP URLs rooted there; otherwise they use an `artifact://` URI.

## Colab launcher

```python
import os
os.environ["RUNTIME_EXECUTION_TOKEN"] = "YOUR_RANDOM_TOKEN"
os.environ["RUNTIME_PORT"] = "8000"

from app.execution.colab_service import serve_forever
serve_forever()
```

The token should be entered through Colab Secrets or another secret mechanism and never committed to Git.
