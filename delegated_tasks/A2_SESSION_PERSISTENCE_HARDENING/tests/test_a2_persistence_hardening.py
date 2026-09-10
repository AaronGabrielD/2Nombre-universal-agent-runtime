"""Candidate A2 regression tests.

These tests are review/integration material only. They target behavior expected after
A2 hardening is integrated; they were not executed by the audit agent because a local
checkout of the repository was unavailable in the execution environment.
"""

import json
import os
import pickle
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.contracts import (
    ArchitecturePlan,
    FinalResult,
    HumanDecision,
    HumanDecisionType,
    WorkerSpec,
)
from app.core.models import RunContext
from app.core.states import WorkflowState
from app.session.json_repository import JsonFileSessionRepository
from app.session.manager import SessionManager
from app.session.models import SessionMessage, SessionRecord, WorkerOutput
from app.session.repository import (
    InMemorySessionRepository,
    SQLiteSessionRepository,
    SessionRepositoryError,
)


class JsonIdentityAndCorruptionTests(unittest.TestCase):
    def test_get_rejects_filename_payload_run_id_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            record = SessionRecord(context=RunContext(run_id="run-a"))
            repository.create(record)

            path = Path(root) / "run-a.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["record"]["context"]["run_id"] = "run-b"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")

    def test_list_rejects_filename_payload_run_id_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))
            path = Path(root) / "run-a.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["record"]["context"]["run_id"] = "run-b"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(SessionRepositoryError):
                repository.list()

    def test_get_rejects_non_object_top_level_json(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            (Path(root) / "broken.json").write_text("[]", encoding="utf-8")

            with self.assertRaises(SessionRepositoryError):
                repository.get("broken")

    def test_get_rejects_wrong_worker_outputs_container_shape(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))
            path = Path(root) / "run-a.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["record"]["worker_outputs"] = []
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")

    def test_get_rejects_invalid_architecture_plan(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))
            path = Path(root) / "run-a.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["record"]["architecture_plan"] = {
                "plan_id": "plan-1",
                "objective": "invalid on purpose",
                "workers": [],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")

    def test_get_rejects_decision_owned_by_another_run(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))
            path = Path(root) / "run-a.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["record"]["decisions"] = [
                {
                    "gate_id": "gate-1",
                    "run_id": "run-b",
                    "decision": "approve",
                    "feedback": "bad ownership",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "actor": "human",
                }
            ]
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")

    def test_get_rejects_final_result_owned_by_another_run(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))
            path = Path(root) / "run-a.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["record"]["final_result"] = {
                "run_id": "run-b",
                "status": "approved",
                "summary": "wrong owner",
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")


class SQLiteIdentityAndValidationTests(unittest.TestCase):
    def test_get_rejects_row_payload_run_id_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            database = os.path.join(root, "runtime.db")
            repository = SQLiteSessionRepository(database)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))

            record = repository.get("run-a")
            record.context.run_id = "run-b"
            payload = sqlite3.Binary(pickle.dumps(record, protocol=pickle.HIGHEST_PROTOCOL))
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE sessions SET payload = ? WHERE run_id = ?",
                    (payload, "run-a"),
                )

            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")

    def test_get_rejects_invalid_pickled_session_record(self):
        with tempfile.TemporaryDirectory() as root:
            database = os.path.join(root, "runtime.db")
            repository = SQLiteSessionRepository(database)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))

            invalid = SessionRecord(
                context=RunContext(run_id="run-a"),
                architecture_plan=ArchitecturePlan(
                    plan_id="plan-1",
                    objective="invalid on purpose",
                    workers=(),
                ),
            )
            payload = sqlite3.Binary(pickle.dumps(invalid, protocol=pickle.HIGHEST_PROTOCOL))
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE sessions SET payload = ? WHERE run_id = ?",
                    (payload, "run-a"),
                )

            with self.assertRaises(SessionRepositoryError):
                repository.get("run-a")


class InMemoryIsolationTests(unittest.TestCase):
    def test_get_returns_isolated_snapshot(self):
        repository = InMemorySessionRepository()
        record = SessionRecord(context=RunContext(run_id="run-a", metadata={"owner": "one"}))
        record.messages.append(SessionMessage(run_id="run-a", role="user", content="hello"))
        repository.create(record)

        leaked = repository.get("run-a")
        leaked.context.metadata["owner"] = "two"
        leaked.messages.append(SessionMessage(run_id="run-a", role="user", content="tampered"))

        stored = repository.get("run-a")
        self.assertEqual(stored.context.metadata["owner"], "one")
        self.assertEqual(len(stored.messages), 1)

    def test_create_does_not_retain_caller_owned_record(self):
        repository = InMemorySessionRepository()
        record = SessionRecord(context=RunContext(run_id="run-a", metadata={"owner": "one"}))
        repository.create(record)
        record.context.metadata["owner"] = "changed-after-create"

        self.assertEqual(repository.get("run-a").context.metadata["owner"], "one")


class SessionManagerReferenceIsolationTests(unittest.TestCase):
    def test_returned_message_metadata_cannot_mutate_stored_session(self):
        manager = SessionManager(repository=InMemorySessionRepository())
        run = manager.create_session()
        message = manager.add_message(
            run.run_id,
            role="user",
            content="hello",
            metadata={"phase": "intake"},
        )
        message.metadata["phase"] = "tampered"

        snapshot = manager.snapshot(run.run_id)
        self.assertEqual(snapshot.messages[0].metadata["phase"], "intake")

    def test_worker_output_mutable_payload_is_detached(self):
        manager = SessionManager(repository=InMemorySessionRepository())
        run = manager.create_session()
        output = WorkerOutput(worker_id="worker-1", run_id=run.run_id, status="ok", output={"value": 1})
        manager.set_worker_output(run.run_id, output)
        output.output["value"] = 2

        snapshot = manager.snapshot(run.run_id)
        self.assertEqual(snapshot.worker_outputs["worker-1"].output["value"], 1)

    def test_final_result_mutable_payload_is_detached(self):
        manager = SessionManager(repository=InMemorySessionRepository())
        run = manager.create_session()
        result = FinalResult(
            run_id=run.run_id,
            status="approved",
            summary="ok",
            deliverables=({"name": "artifact"},),
        )
        manager.set_final_result(run.run_id, result)
        result.deliverables[0]["name"] = "tampered"

        snapshot = manager.snapshot(run.run_id)
        self.assertEqual(snapshot.final_result.deliverables[0]["name"], "artifact")


class JsonSymlinkHardeningTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support unavailable")
    def test_get_rejects_symlink_session_file(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            repository.create(SessionRecord(context=RunContext(run_id="real")))
            os.symlink(Path(root) / "real.json", Path(root) / "alias.json")

            with self.assertRaises(SessionRepositoryError):
                repository.get("alias")


class ExistingInvariantControlsTests(unittest.TestCase):
    def test_valid_waiting_state_remains_representable(self):
        context = RunContext(run_id="run-a", state=WorkflowState.WAITING_ARCHITECT_APPROVAL)
        plan = ArchitecturePlan(
            plan_id="plan-1",
            objective="valid plan",
            workers=(WorkerSpec("worker-1", "builder", "build"),),
        )
        decision = HumanDecision(
            gate_id="gate-1",
            run_id="run-a",
            decision=HumanDecisionType.APPROVE,
            feedback="ok",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        record = SessionRecord(
            context=context,
            architecture_plan=plan,
            decisions=[decision],
        )
        record.validate()


if __name__ == "__main__":
    unittest.main()
