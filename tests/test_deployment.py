import unittest

from app.deployment.models import DeploymentEnvironment, DeploymentSpec
from app.deployment.service import DeploymentPlanner, DockerComposeDeploymentAdapter


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.planner = DeploymentPlanner()
        self.adapter = DockerComposeDeploymentAdapter()

    def test_valid_spec_renders_without_deploying(self):
        spec = DeploymentSpec(
            name="runtime",
            command=("python", "-m", "app.ui.chainlit_app"),
            port=8000,
            environment=(
                DeploymentEnvironment("APP_MODE", value="production", secret=False),
                DeploymentEnvironment("CHAINLIT_AUTH_SECRET", secret=True, value="super-secret"),
            ),
        )
        render = self.planner.render(self.adapter, spec)
        self.assertEqual(render.provider, "docker-compose")
        compose = dict(render.files)["docker-compose.yml"]
        self.assertIn("${CHAINLIT_AUTH_SECRET}", compose)
        self.assertNotIn("super-secret", compose)

    def test_invalid_port_is_rejected(self):
        spec = DeploymentSpec(
            name="runtime", command=("python", "-m", "app"), port=70000
        )
        with self.assertRaises(ValueError):
            self.planner.validate(spec)

    def test_duplicate_environment_keys_are_rejected(self):
        spec = DeploymentSpec(
            name="runtime",
            command=("python", "-m", "app"),
            port=8000,
            environment=(DeploymentEnvironment("A"), DeploymentEnvironment("A")),
        )
        with self.assertRaises(ValueError):
            self.planner.validate(spec)


if __name__ == "__main__":
    unittest.main()
