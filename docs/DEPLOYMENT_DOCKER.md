# Docker deployment

This image runs the Chainlit presentation layer and runtime coordinator as a non-root process.

## Build

```bash
docker build -t universal-agent-runtime:local .
```

The image includes the Docker CLI only for `EXECUTION_BACKEND=docker`; the Docker daemon remains an explicit host/deployment responsibility.

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

Gemini-backed Architect/Worker/Supervisor agents additionally require `GEMINI_API_KEY`.

For `EXECUTION_BACKEND=colab`, also configure the gateway URL and token. For `EXECUTION_BACKEND=docker`, the host must provide a Docker daemon reachable through the Docker CLI; the image does not run Docker-in-Docker.

## Docker backend on a local Linux host

When the runtime container itself must launch child Docker containers, provide the host Docker socket and the socket's group ID while keeping the runtime process non-root:

```bash
DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
docker run --rm \
  -p 8000:8000 \
  -v uar-data:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --group-add "$DOCKER_GID" \
  --env-file .env \
  universal-agent-runtime:local
```

This socket grants the runtime process broad control of the host Docker daemon. It is suitable for a controlled single-operator deployment, but it is not a high-assurance multi-tenant security boundary. A production multi-tenant deployment should use a separately isolated execution service instead.

## Persistent storage

Mount `/data` to durable storage. The runtime keeps durable session and identity SQLite files there by default.

## Security posture

The container runs as the dedicated `uar` user. Runtime state is kept outside the application tree. `.dockerignore` excludes secrets and local runtime databases from the build context.

The image is not a hostile multi-tenant sandbox. Execution isolation remains an explicit backend responsibility, and network/provider boundaries must still be enforced by the deployment environment.

## CrewAI integration

CrewAI remains optional. When the `crewai` package is installed, the runtime uses `CrewAIWorkerAdapter`; otherwise it falls back to the native `GeminiWorkerAdapter`, preserving the runtime's execution and approval boundaries.

Install the optional CrewAI integration with:

```bash
pip install -r requirements-crewai.txt
```
