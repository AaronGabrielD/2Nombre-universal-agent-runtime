"""Candidate regressions for the residual A2 defects on current main.

These are deliberately kept outside the real project test tree. They describe the
expected behavior after the proposed hardening is integrated by the project lead.
They have NOT been executed by this delegated audit agent.
"""

import json
import os
import pickle
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.contracts import ArchitecturePlan, WorkerSpec
from app.core.models import RunContext
from app.session.json_repository import JsonFileSessionRepository
from app.session.models import SessionRecord
from app.session.repository import InMemorySessionRepository, SQLiteSessionRepository, SessionRepositoryError


class SQLiteResidualIntegrityTests(unittest.TestCase):
    def test_row_key_and_payload_run_id_must_match(self):
        with tempfile.TemporaryDirectory() as root:
            database = str(Path(root) / "sessions.db")
            SQLiteSessionRepository(database)
            payload_record = SessionRecord(context=RunContext(run_id="run-b"))
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "INSERT INTO sessions(run_id, payload) VALUES (?, ?)",
                    ("run-a", sqlite3.Binary(pickle.dumps(payload_record))),
                )

            repository = SQLiteSessionRepository(database)
            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")

    def test_malformed_session_context_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            database = str(Path(root) / "sessions.db")
            SQLiteSessionRepository(database)
            malformed = SessionRecord(context=None)  # type: ignore[arg-type]
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "INSERT INTO sessions(run_id, payload) VALUES (?, ?)",
                    ("run-a", sqlite3.Binary(pickle.dumps(malformed))),
                )

            repository = SQLiteSessionRepository(database)
            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")

    def test_sqlite_create_rejects_invalid_architecture_plan(self):
        with tempfile.TemporaryDirectory() as root:
            database = str(Path(root) / "sessions.db")
            repository = SQLiteSessionRepository(database)
            record = SessionRecord(
                context=RunContext(run_id="run-a"),
                architecture_plan=ArchitecturePlan(
                    plan_id="plan-1",
                    objective="invalid",
                    workers=(),
                ),
            )
            with self.assertRaises(SessionRepositoryError):
                repository.create(record)


class InMemoryAliasIsolationTests(unittest.TestCase):
    def test_get_returns_detached_record(self):
        repository = InMemorySessionRepository()
        record = SessionRecord(context=RunContext(run_id="run-a", metadata={"owner": "one"}))
        repository.create(record)

        returned = repository.get("run-a")
        returned.context.metadata["owner"] = "tampered"

        self.assertEqual(repository.get("run-a").context.metadata["owner"], "one")

    def test_create_does_not_retain_caller_mutations(self):
        repository = InMemorySessionRepository()
        record = SessionRecord(context=RunContext(run_id="run-a", metadata={"owner": "one"}))
        repository.create(record)
        record.context.metadata["owner"] = "tampered"

        self.assertEqual(repository.get("run-a").context.metadata["owner"], "one")


class JsonResidualShapeTests(unittest.TestCase):
    def test_wrong_worker_outputs_container_is_repository_error(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))
            path = Path(root) / "run-a.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["record"]["worker_outputs"] = []
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")

    def test_wrong_messages_container_is_repository_error(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))
            path = Path(root) / "run-a.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["record"]["messages"] = {"not": "a-list"}
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")


if __name__ == "__main__":
    unittest.main()
