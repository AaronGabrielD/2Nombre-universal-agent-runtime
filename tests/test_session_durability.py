import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.core.contracts import ArtifactRef, ExecutionResult, ExecutionStatus, HumanDecision, HumanDecisionType
from app.session.json_repository import JsonFileSessionRepository
from app.session.manager import SessionManager
from app.session.repository import SQLiteSessionRepository, SessionNotFoundError, SessionRepositoryError


class SessionDurabilityTests(unittest.TestCase):
    def _populate_session(self, manager: SessionManager):
        context = manager.create_session(metadata={"owner": "test", "purpose": "durability"})
        manager.add_message(context.run_id, role="user", content="persist me", metadata={"source": "test"})
        manager.add_artifact(context.run_id, ArtifactRef("artifact-1", "report.txt", "text/plain"))
        manager.add_decision(
            context.run_id,
            HumanDecision(
                gate_id="gate-a",
                run_id=context.run_id,
                decision=HumanDecisionType.APPROVE,
                feedback="approved",
                timestamp="2026-09-10T00:00:00+00:00",
            ),
        )
        manager.add_execution_result(
            context.run_id,
            ExecutionResult(
                execution_id="exec-1",
                status=ExecutionStatus.SUCCESS,
                exit_code=0,
                stdout="ok",
                stderr="",
                duration_ms=10,
                artifacts=(ArtifactRef("artifact-2", "out.txt", "text/plain"),),
                backend="test",
            ),
        )
        return context

    def test_json_survives_manager_restart_with_full_session_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonFileSessionRepository(temp_dir)
            first_manager = SessionManager(repository)
            context = self._populate_session(first_manager)

            second_manager = SessionManager(JsonFileSessionRepository(temp_dir))
            snapshot = second_manager.snapshot(context.run_id)

            self.assertEqual(snapshot.context.run_id, context.run_id)
            self.assertEqual(snapshot.context.metadata["owner"], "test")
            self.assertEqual(snapshot.messages[0].content, "persist me")
            self.assertEqual(snapshot.artifacts[0].artifact_id, "artifact-1")
            self.assertEqual(snapshot.decisions[0].decision, HumanDecisionType.APPROVE)
            self.assertEqual(snapshot.execution_results[0].status, ExecutionStatus.SUCCESS)
            self.assertEqual(snapshot.execution_results[0].artifacts[0].artifact_id, "artifact-2")

    def test_sqlite_survives_manager_restart_with_full_session_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "sessions.db")
            first_manager = SessionManager(SQLiteSessionRepository(database_path))
            context = self._populate_session(first_manager)

            second_manager = SessionManager(SQLiteSessionRepository(database_path))
            snapshot = second_manager.snapshot(context.run_id)

            self.assertEqual(snapshot.context.run_id, context.run_id)
            self.assertEqual(snapshot.context.metadata["purpose"], "durability")
            self.assertEqual(len(snapshot.messages), 1)
            self.assertEqual(len(snapshot.decisions), 1)
            self.assertEqual(snapshot.execution_results[0].execution_id, "exec-1")

    def test_json_rejects_corrupt_document_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "run-1.json"
            path.write_text("{not valid json", encoding="utf-8")
            repository = JsonFileSessionRepository(temp_dir)

            with self.assertRaises(SessionRepositoryError):
                repository.get("run-1")

    def test_json_rejects_tampered_contract_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "run-1.json"
            path.write_text(
                '{"schema_version":1,"record":{"context":{"run_id":"run-1","state":"IDLE",'
                '"created_at":"2026-09-10T00:00:00+00:00","updated_at":"2026-09-10T00:00:00+00:00",'
                '"metadata":{}},"execution_results":[{"execution_id":"exec-1","status":"bogus",'
                '"exit_code":0,"stdout":"","stderr":"","duration_ms":0,"artifacts":[],"backend":"test"}]}}',
                encoding="utf-8",
            )
            repository = JsonFileSessionRepository(temp_dir)

            with self.assertRaises((SessionRepositoryError, ValueError)):
                repository.get("run-1")

    def test_json_rejects_unsafe_run_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonFileSessionRepository(temp_dir)
            for run_id in ("../escape", "nested/run", "nested\\run", "bad\x00id", "bad\nid", " "):
                with self.assertRaises(ValueError):
                    repository.get(run_id)

    def test_sqlite_rejects_corrupt_payload_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "sessions.db")
            repository = SQLiteSessionRepository(database_path)
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "INSERT INTO sessions(run_id, payload) VALUES (?, ?)",
                    ("corrupt-run", sqlite3.Binary(b"not-a-pickle")),
                )

            with self.assertRaises(SessionRepositoryError):
                repository.get("corrupt-run")

    def test_missing_session_operations_fail_with_typed_error(self):
        repository = JsonFileSessionRepository(tempfile.mkdtemp())
        with self.assertRaises(SessionNotFoundError):
            repository.get("missing")
        with self.assertRaises(SessionNotFoundError):
            repository.delete("missing")

    def test_manager_serializes_concurrent_session_updates(self):
        manager = SessionManager()
        context = manager.create_session()

        def add_message(index: int):
            manager.add_message(context.run_id, role="worker", content=f"message-{index}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(add_message, range(40)))

        messages = manager.snapshot(context.run_id).messages
        self.assertEqual(len(messages), 40)
        self.assertEqual({message.content for message in messages}, {f"message-{i}" for i in range(40)})

    def test_execution_results_remain_scoped_to_target_run(self):
        manager = SessionManager()
        first = manager.create_session()
        second = manager.create_session()
        result = ExecutionResult(
            execution_id="exec-first",
            status=ExecutionStatus.SUCCESS,
            exit_code=0,
            stdout="first",
            stderr="",
            duration_ms=1,
            backend="test",
        )

        manager.add_execution_result(first.run_id, result)

        self.assertEqual(len(manager.snapshot(first.run_id).execution_results), 1)
        self.assertEqual(len(manager.snapshot(second.run_id).execution_results), 0)


if __name__ == "__main__":
    unittest.main()
