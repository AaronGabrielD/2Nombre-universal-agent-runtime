import tempfile
import unittest
from pathlib import Path

from app.approval.models import GateStatus
from app.approval.service import HumanApprovalEngine
from app.core.contracts import HumanDecisionType
from app.session.json_repository import JsonFileSessionRepository
from app.session.manager import SessionManager
from app.session.repository import SQLiteSessionRepository


class ApprovalGatePersistenceTests(unittest.TestCase):
    def _exercise_repository(self, repository):
        first_sessions = SessionManager(repository=repository)
        run_id = first_sessions.create_session().run_id

        first_engine = HumanApprovalEngine(session_manager=first_sessions)
        gate = first_engine.request_gate(
            run_id=run_id,
            kind="ARCHITECTURE",
            title="Gate A",
            prompt="Approve the architecture",
        )

        restarted_sessions = SessionManager(repository=repository)
        restarted_engine = HumanApprovalEngine(session_manager=restarted_sessions)

        restored = restarted_engine.list_open_gates(run_id=run_id)
        self.assertEqual(tuple(item.gate_id for item in restored), (gate.gate_id,))
        self.assertEqual(restored[0].status, GateStatus.OPEN)

        decision = restarted_engine.resolve_gate(
            gate_id=gate.gate_id,
            decision=HumanDecisionType.APPROVE,
            feedback="approved after restart",
            actor="human",
        )
        self.assertEqual(decision.run_id, run_id)
        self.assertEqual(restarted_engine.get_gate(gate.gate_id).status, GateStatus.RESOLVED)
        self.assertEqual(restarted_engine.get_decision(gate.gate_id), decision)

        final_sessions = SessionManager(repository=repository)
        final_engine = HumanApprovalEngine(session_manager=final_sessions)
        restored_final = final_engine.get_gate(gate.gate_id)
        self.assertEqual(restored_final.status, GateStatus.RESOLVED)
        self.assertEqual(final_engine.get_decision(gate.gate_id), decision)
        self.assertEqual(final_engine.list_open_gates(run_id=run_id), ())

    def test_json_gate_and_decision_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._exercise_repository(JsonFileSessionRepository(tmp))

    def test_sqlite_gate_and_decision_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            repository = SQLiteSessionRepository(str(Path(tmp) / "sessions.db"))
            self._exercise_repository(repository)

    def test_old_json_session_without_gate_field_remains_loadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = SessionManager(repository=JsonFileSessionRepository(tmp))
            run_id = sessions.create_session().run_id
            path = Path(tmp) / f"{run_id}.json"
            payload = path.read_text(encoding="utf-8")
            self.assertIn("\"approval_gates\"", payload)
            path.write_text(payload.replace(',\n    "approval_gates": []', '', 1), encoding="utf-8")

            restarted = SessionManager(repository=JsonFileSessionRepository(tmp))
            engine = HumanApprovalEngine(session_manager=restarted)
            self.assertEqual(engine.list_open_gates(run_id=run_id), ())


if __name__ == "__main__":
    unittest.main()
