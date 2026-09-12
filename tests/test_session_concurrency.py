"""Regression tests for session concurrency control."""
from __future__ import annotations

import pickle
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from app.core.contracts import ExecutionResult, ExecutionStatus
from app.core.models import RunContext
from app.session.manager import SessionManager
from app.session.models import SessionRecord, WorkerOutput
from app.session.repository import (
    InMemorySessionRepository,
    SQLiteSessionRepository,
    SessionRepositoryConflictError,
)


class SessionConcurrencyTests(unittest.TestCase):
    def test_concurrent_execution_results_are_not_lost(self):
        sessions = SessionManager()
        context = sessions.create_session()
        barrier = threading.Barrier(8)
        errors = []
        errors_lock = threading.Lock()

        def writer(index: int) -> None:
            try:
                barrier.wait()
                sessions.add_execution_result(
                    context.run_id,
                    ExecutionResult(
                        execution_id=f"exec-{index}",
                        status=ExecutionStatus.SUCCESS,
                        exit_code=0,
                        stdout="ok",
                        stderr="",
                        duration_ms=1,
                        backend="test",
                    ),
                )
            except Exception as exc:  # pragma: no cover - assertion below reports failures
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        results = sessions.snapshot(context.run_id).execution_results
        self.assertEqual(len(results), 8)
        self.assertEqual({item.execution_id for item in results}, {f"exec-{i}" for i in range(8)})

    def test_snapshot_isolated_during_concurrent_worker_updates(self):
        sessions = SessionManager()
        context = sessions.create_session()
        start_writers = threading.Event()
        errors = []
        errors_lock = threading.Lock()

        def writer(index: int) -> None:
            try:
                start_writers.wait()
                sessions.set_worker_output(
                    context.run_id,
                    WorkerOutput(
                        worker_id=f"worker-{index}",
                        run_id=context.run_id,
                        status="success",
                        output={"worker_index": index},
                    ),
                )
            except Exception as exc:  # pragma: no cover - assertion below reports failures
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        snapshot_before = sessions.snapshot(context.run_id)
        start_writers.set()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(snapshot_before.worker_outputs, {})
        final = sessions.snapshot(context.run_id).worker_outputs
        self.assertEqual(len(final), 4)
        self.assertEqual(set(final), {f"worker-{i}" for i in range(4)})
        self.assertEqual({output.output["worker_index"] for output in final.values()}, {0, 1, 2, 3})

    def test_in_memory_save_increments_revision_and_rejects_stale_record(self):
        repository = InMemorySessionRepository()
        record = SessionRecord(context=RunContext())
        repository.create(record)
        stale = repository.get(record.context.run_id)

        record.context.metadata["writer"] = "first"
        repository.save(record)

        stale.context.metadata["writer"] = "stale"
        with self.assertRaises(SessionRepositoryConflictError):
            repository.save(stale)

        stored = repository.get(record.context.run_id)
        self.assertEqual(stored.revision, 1)
        self.assertEqual(stored.context.metadata["writer"], "first")

    def test_sqlite_rejects_stale_writer_from_second_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = str(Path(tmpdir) / "sessions.db")
            first = SQLiteSessionRepository(database_path)
            second = SQLiteSessionRepository(database_path)
            record = SessionRecord(context=RunContext())
            first.create(record)

            stale = second.get(record.context.run_id)
            current = first.get(record.context.run_id)
            current.context.metadata["writer"] = "first"
            first.save(current)

            stale.context.metadata["writer"] = "stale"
            with self.assertRaises(SessionRepositoryConflictError):
                second.save(stale)

            stored = first.get(record.context.run_id)
            self.assertEqual(stored.revision, 1)
            self.assertEqual(stored.context.metadata["writer"], "first")

    def test_sqlite_migrates_legacy_schema_without_revision_column(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = str(Path(tmpdir) / "legacy.db")
            record = SessionRecord(context=RunContext())
            payload = sqlite3.Binary(pickle.dumps(record, protocol=pickle.HIGHEST_PROTOCOL))
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "CREATE TABLE sessions (run_id TEXT PRIMARY KEY, payload BLOB NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO sessions(run_id, payload) VALUES (?, ?)",
                    (record.context.run_id, payload),
                )

            repository = SQLiteSessionRepository(database_path)
            loaded = repository.get(record.context.run_id)
            self.assertEqual(loaded.revision, 0)
            loaded.context.metadata["migrated"] = "yes"
            repository.save(loaded)
            self.assertEqual(repository.get(record.context.run_id).revision, 1)


if __name__ == "__main__":
    unittest.main()
