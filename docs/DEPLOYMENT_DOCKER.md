# Docker deployment

This image runs the Chainlit presentation layer and runtime coordinator as a non-root process.

## Build

```bash
docker build -t universal-agent-runtime:local .
```

## Required production configuration

Provide secrets and runtime settings through the environment or an external secret store. Do not bake `.env` files, databases, API keys, or provider tokens into the image.

At minimum, configure:

- `CHAINLIT_AUTH_SECRET`
- `UAR_EXECUTION_AUTH_SECRET` (32+ random characters unless `EXECUTION_BACKEND=test`)
- `UAR_AUTH_USERNAME`
- `UAR_AUTH_PASSWORD_HASH`
- `UAR_IDENTITY_DB_PATH=/data/runtime_users.db`
- `UAR_SESSION_REPOSITORY=sqlite`
- `UAR_SESSION_REPOSITORY_PATH=/data/runtime_sessions.db`
- `EXECUTION_BACKEND`

For `EXECUTION_BACKEND=colab`, also configure the gateway URL and token. For `EXECUTION_BACKEND=docker`, the host must provide a Docker daemon reachable by the configured Docker backend; this image intentionally does not install Docker-in-Docker or manufacture that trust boundary.

## Persistent storage

Mount `/data` to durable storage. The runtime keeps durable session and identity SQLite files there by default.

Example:

```bash
docker run --rm \
  -p 8000:8000 \
  -v uar-data:/data \
  --env-file .env \
  universal-agent-runtime:local
```

## Security posture

The container runs as the dedicated `uar` user. Runtime state is kept outside the application tree. `.dockerignore` excludes secrets and local runtime databases from the build context.

The image is not a hostile multi-tenant sandbox. Execution isolation remains an explicit backend responsibility, and network/provider boundaries must still be enforced by the deployment environment.
