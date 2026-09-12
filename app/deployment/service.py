"""Provider-neutral deployment planning and rendering boundary."""
from __future__ import annotations

import json
from typing import Protocol
from .models import DeploymentRender, DeploymentSpec


class DeploymentAdapterError(RuntimeError):
    """Raised when a deployment adapter cannot render a deployment."""


class DeploymentAdapter(Protocol):
    provider: str
    def render(self, spec: DeploymentSpec) -> DeploymentRender: ...


class DeploymentPlanner:
    def validate(self, spec: DeploymentSpec) -> DeploymentSpec:
        spec.validate()
        return spec

    def render(self, adapter: DeploymentAdapter, spec: DeploymentSpec) -> DeploymentRender:
        self.validate(spec)
        result = adapter.render(spec)
        if result.provider != adapter.provider:
            raise DeploymentAdapterError(f"deployment adapter returned provider {result.provider!r}; expected {adapter.provider!r}")
        return result


class DockerComposeDeploymentAdapter:
    """Render a minimal Docker Compose service without invoking Docker."""
    provider = "docker-compose"

    def render(self, spec: DeploymentSpec) -> DeploymentRender:
        spec.validate()
        env_lines = []
        for item in spec.environment:
            value = f"${{{item.key}}}" if item.secret else (item.value or "")
            env_lines.append(f"      {json.dumps(item.key)}: {json.dumps(value)}")
        environment = "\n".join(env_lines) if env_lines else "      {}"
        command = json.dumps(list(spec.command), ensure_ascii=False)
        working_directory = json.dumps(spec.working_directory, ensure_ascii=False)
        health_url = f"http://127.0.0.1:{spec.port}{spec.health_path}"
        health_command = "python -c " + json.dumps(
            "import urllib.request; urllib.request.urlopen(" + repr(health_url) + ")",
            ensure_ascii=False,
        )
        compose = (
            "services:\n"
            f"  {spec.name}:\n"
            "    build: .\n"
            f"    working_dir: {working_directory}\n"
            f"    command: {command}\n"
            f"    ports:\n      - {json.dumps(f'{spec.port}:{spec.port}')}\n"
            f"    environment:\n{environment}\n"
            "    restart: unless-stopped\n"
            "    healthcheck:\n"
            f"      test: [\"CMD-SHELL\", {json.dumps(health_command)}]\n"
            "      interval: 30s\n"
            "      timeout: 5s\n"
            "      retries: 3\n"
        )
        instructions = (
            "Review generated configuration before deployment.",
            "Populate secret environment variables in the target secret store; do not commit them.",
            "Expose the configured port only where required by the deployment environment.",
        )
        return DeploymentRender(provider=self.provider, files=(("docker-compose.yml", compose),), instructions=instructions)
