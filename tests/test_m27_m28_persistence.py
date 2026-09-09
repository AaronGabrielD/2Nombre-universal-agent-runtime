import json
import tempfile
import unittest
from pathlib import Path

from app.core.contracts import ArchitecturePlan, HumanDecision, HumanDecisionType, WorkerSpec
from app.core.models import RunContext
from app.execution.docker_backend import DockerExecutionBackend
from app.persistence.migrations import Migration, MigrationError, MigrationRunner
from app.session.json_repository import JsonFileSessionRepository
from app.session.models import SessionMessage, SessionRecord


class M27M28Tests(unittest.TestCase):
    def test_docker_backend_declares_hardened_defaults(self):
        backend = DockerExecutionBackend()
        self.assertEqual(backend.info.backend_id, "docker")
        command = backend._docker_command(
            type("Request", (), {"needs_network": False, "environment": {}})(),
            Path(tempfile.gettempdir()),
        )
        joined = " ".join(command)
        self.assertIn("--network none", joined)
        self.assertIn("--read-only", joined)
        self.assertIn("--cap-drop ALL", joined)
        self.assertIn("--security-opt no-new-privileges:true", joined)
        self.assertIn("--pids-limit 128", joined)

    def test_json_session_repository_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonFileSessionRepository(temp_dir)
            context = RunContext(metadata={"owner_user_id": "user-1"})
            record = SessionRecord(context=context)
            record.messages.append(SessionMessage(run_id=context.run_id, role="user", content="hello"))
            record.architecture_plan = ArchitecturePlan(
                plan_id="p1", objective="test",
                workers=(WorkerSpec("w1", "builder", "build", required_tools=("calculator",)),),
            )
            record.decisions.append(
                HumanDecision("gate-1", context.run_id, HumanDecisionType.APPROVE, "ok", "2026-01-01T00:00:00+00:00")
            )
            repository.create(record)
            restored = repository.get(context.run_id)
            self.assertEqual(restored.context.metadata["owner_user_id"], "user-1")
            self.assertEqual(restored.messages[0].content, "hello")
            self.assertEqual(restored.architecture_plan.workers[0].required_tools, ("calculator",))
            self.assertEqual(restored.decisions[0].decision, HumanDecisionType.APPROVE)

    def test_json_repository_uses_schema_version_and_atomic_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonFileSessionRepository(temp_dir)
            context = RunContext()
            repository.create(SessionRecord(context=context))
            path = Path(temp_dir) / f"{context.run_id}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())

    def test_migration_runner_applies_each_version_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = str(Path(temp_dir) / "test.db")
            calls = []

            def v1(connection):
                calls.append(1)
                connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")

            def v2(connection):
                calls.append(2)
                connection.execute("INSERT INTO sample(value) VALUES ('ok')")

            runner = MigrationRunner(database, [Migration(1, "create sample", v1), Migration(2, "seed sample", v2)])
            self.assertEqual(runner.migrate(), 2)
            self.assertEqual(runner.migrate(), 2)
            self.assertEqual(calls, [1, 2])

    def test_migration_failure_rolls_back_and_reports_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = str(Path(temp_dir) / "test.db")

            def broken(connection):
                connection.execute("CREATE TABLE sample(value TEXT)")
                raise RuntimeError("boom")

            runner = MigrationRunner(database, [Migration(1, "broken", broken)])
            with self.assertRaises(MigrationError):
                runner.migrate()
            self.assertEqual(runner.current_version(), 0)


if __name__ == "__main__":
    unittest.main()
