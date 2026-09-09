"""Provider-neutral deployment planning and rendering boundary."""
from __future__ import annotations

from typing import Protocol

from .models import DeploymentRender, DeploymentSpec


class DeploymentAdapterError(RuntimeError):
    """Raised when a deployment adapter cannot render a deployment."""


class DeploymentAdapter(Protocol):
    provider: str

    def render(self, spec: DeploymentSpec) -> DeploymentRender: ...


class DeploymentPlanner:
    """Validate a portable deployment spec before handing it to a provider adapter."""

    def validate(self, spec: DeploymentSpec) -> DeploymentSpec:
        spec.validate()
        return spec

    def render(self, adapter: DeploymentAdapter, spec: DeploymentSpec) -> DeploymentRender:
        self.validate(spec)
        result = adapter.render(spec)
        if result.provider != adapter.provider:
            raise DeploymentAdapterError(
                f"deployment adapter returned provider {result.provider!r}; expected {adapter.provider!r}"
            )
        return result


class DockerComposeDeploymentAdapter:
    """Render a minimal Docker Compose service without invoking Docker."""

    provider = "docker-compose"

    def render(self, spec: DeploymentSpec) -> DeploymentRender:
        spec.validate()
        env_lines = []
        for item in spec.environment:
            value = item.value if item.value is not None else ""
            if item.secret and item.value is not None:
                value = "${%s}" % item.key
            env_lines.append(f"      {item.key}: {value!r}")
        environment = "\n".join(env_lines) if env_lines else "      { }"
        command = "[" + ", ".join(repr(part) for part in spec.command) + "]"
        compose = (
            "services:\n"
            f"  {spec.name}:\n"
            "    build: .\n"
            f"    working_dir: {spec.working_directory!r}\n"
            f"    command: {command}\n"
            f"    ports:\n      - \"{spec.port}:{spec.port}\"\n"
            f"    environment:\n{environment}\n"
            "    restart: unless-stopped\n"
            "    healthcheck:\n"
            f"      test: [\"CMD-SHELL\", \"python -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:{spec.port}{spec.health_path}\")'\"]\n"
            "      interval: 30s\n"
            "      timeout: 5s\n"
            "      retries: 3\n"
        )
        instructions = (
            "Review generated configuration before deployment.",
            "Populate secret environment variables in the target secret store; do not commit them.",
            "Expose the configured port only where required by the deployment environment.",
        )
        return DeploymentRender(
            provider=self.provider,
            files=(("docker-compose.yml", compose),),
            instructions=instructions,
        )
