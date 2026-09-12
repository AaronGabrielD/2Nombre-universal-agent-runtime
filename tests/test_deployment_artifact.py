from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeploymentArtifactTests(unittest.TestCase):
    def test_dockerfile_exists_and_runs_chainlit_non_root(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM python:3.12-slim", dockerfile)
        self.assertIn("USER uar", dockerfile)
        self.assertIn('CMD ["chainlit", "run", "app/ui/chainlit_app.py", "--host", "0.0.0.0", "--port", "8000"]', dockerfile)
        self.assertIn("UAR_SESSION_REPOSITORY_PATH=/data/runtime_sessions.db", dockerfile)
        self.assertIn("UAR_IDENTITY_DB_PATH=/data/runtime_users.db", dockerfile)

    def test_dockerignore_excludes_runtime_secrets_and_databases(self):
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        for entry in (".env", "*.db", "*.sqlite", "runtime-*artifacts"):
            self.assertIn(entry, dockerignore)


if __name__ == "__main__":
    unittest.main()
