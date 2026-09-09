# M25 — Provider-Neutral Deployment Adapter

M25 introduces a deployment boundary separate from the application/runtime logic.

`DeploymentSpec` describes an application name, command, port, health endpoint, working directory, and environment declarations. `DeploymentPlanner` validates the spec and delegates rendering to a provider-specific adapter.

The initial adapter renders Docker Compose only; it does not invoke Docker, open ports, upload images, or contact a cloud provider. Secret values are rendered as environment-variable references instead of being embedded in generated deployment files.

This keeps Google Colab, Docker-based hosting, or a future free/cloud provider as interchangeable operational targets rather than hard-coded runtime dependencies.
