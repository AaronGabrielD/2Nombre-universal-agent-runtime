# M27 — Stronger execution isolation

M27 adds an optional Docker execution backend behind the existing M08 `ExecutionBackend` contract.

## Controls

The backend requests a dedicated container with:

- `--network none` by default;
- read-only container root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges` enabled;
- PID limit;
- memory and CPU limits;
- a small `tmpfs` for temporary writable data;
- a non-root numeric user;
- an isolated temporary workspace mounted only for the execution;
- `shell=False` in the host-side Docker invocation;
- bounded stdout/stderr.

The Docker image is not pulled automatically. The default command uses `--pull=never` so a missing image fails instead of silently changing the execution environment.

## Boundary

This is substantially stronger than executing generated Python directly in the web process, but container isolation is not equivalent to a high-assurance VM or hostile multi-tenant sandbox. Docker daemon security, kernel isolation, image provenance, resource limits, and host configuration remain part of the deployment threat model.

The M23 static Python admission policy remains useful defense in depth for the Colab backend. M27 does not remove the requirement for M08 authorization or human Gate C approval for risky tools.

## Configuration

The backend is provider-neutral from the orchestrator's perspective. A deployment can register both `colab` and `docker` backends and select one through the existing execution-gateway policy.

No Docker dependency is required in Python; the backend discovers the Docker CLI at runtime and reports `available=false` when it is absent.
