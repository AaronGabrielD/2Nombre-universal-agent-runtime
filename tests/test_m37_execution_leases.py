import tempfile
import unittest
from pathlib import Path

from app.execution.lease import ExecutionLeaseError, ExecutionLeaseService
from app.session.json_repository import JsonFileSessionRepository
from app.session.manager import SessionManager


class M37ExecutionLeaseTests(unittest.TestCase):
    def test_completed_lease_survives_service_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonFileSessionRepository(directory)
            sessions = SessionManager(repository)
            run = sessions.create_session()
            first = ExecutionLeaseService(session_manager=sessions)
            key = first.idempotency_key(
                run_id=run.run_id,
                worker_id="w1",
                task_id="t1",
                language="python",
                code="print(1)",
            )
            lease = first.reserve(
                run_id=run.run_id,
                worker_id="w1",
                task_id="t1",
                idempotency_key=key,
                execution_id="exec-1",
            )
            first.complete(run_id=run.run_id, lease_id=lease.lease_id)

            second = ExecutionLeaseService(session_manager=SessionManager(repository))
            recovered = second.reserve(
                run_id=run.run_id,
                worker_id="w1",
                task_id="t1",
                idempotency_key=key,
                execution_id="exec-2",
            )
            self.assertEqual(recovered.status, "COMPLETED")
            self.assertEqual(recovered.execution_id, "exec-1")

    def test_active_lease_blocks_replay(self):
        sessions = SessionManager()
        run = sessions.create_session()
        service = ExecutionLeaseService(session_manager=sessions)
        key = service.idempotency_key(
            run_id=run.run_id,
            worker_id="w1",
            task_id="t1",
            language="python",
            code="print(1)",
        )
        service.reserve(
            run_id=run.run_id,
            worker_id="w1",
            task_id="t1",
            idempotency_key=key,
            execution_id="exec-1",
        )
        with self.assertRaises(ExecutionLeaseError):
            service.reserve(
                run_id=run.run_id,
                worker_id="w1",
                task_id="t1",
                idempotency_key=key,
                execution_id="exec-2",
            )

    def test_key_changes_when_code_changes(self):
        sessions = SessionManager()
        run = sessions.create_session()
        service = ExecutionLeaseService(session_manager=sessions)
        first = service.idempotency_key(run_id=run.run_id, worker_id="w1", task_id="t1", language="python", code="print(1)")
        second = service.idempotency_key(run_id=run.run_id, worker_id="w1", task_id="t1", language="python", code="print(2)")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
