import threading
import unittest

from app.approval.models import GateStatus
from app.approval.service import ApprovalError, HumanApprovalEngine
from app.core.contracts import HumanDecisionType


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.engine = HumanApprovalEngine()

    def test_creates_and_filters_open_gate(self):
        gate = self.engine.request_gate(
            run_id="run-1",
            kind="architecture",
            title="Approve plan",
            prompt="Review plan",
            context={"workers": 3},
        )
        self.assertEqual(gate.status, GateStatus.OPEN)
        self.assertEqual(len(self.engine.list_open_gates(run_id="run-1")), 1)
        self.assertEqual(len(self.engine.list_open_gates(run_id="run-2")), 0)

    def test_resolves_with_approval_and_records_history(self):
        gate = self.engine.request_gate(
            run_id="run-1", kind="architecture", title="Approve", prompt="Approve?"
        )
        decision = self.engine.resolve_gate(
            gate_id=gate.gate_id,
            decision=HumanDecisionType.APPROVE,
            feedback="Looks good",
            actor="owner",
            timestamp="2026-09-08T20:00:00+00:00",
        )
        self.assertEqual(decision.run_id, "run-1")
        self.assertEqual(self.engine.get_gate(gate.gate_id).status, GateStatus.RESOLVED)
        self.assertEqual(self.engine.get_decision(gate.gate_id), decision)
        self.assertEqual(self.engine.get_decision_history(gate.gate_id), (decision,))

    def test_supports_modify_reject_and_clarify(self):
        for index, choice in enumerate(
            (HumanDecisionType.MODIFY, HumanDecisionType.REJECT, HumanDecisionType.CLARIFY)
        ):
            gate = self.engine.request_gate(
                run_id=f"run-{index}", kind="k", title="t", prompt="p"
            )
            self.assertEqual(
                self.engine.resolve_gate(gate_id=gate.gate_id, decision=choice, feedback="f").decision,
                choice,
            )

    def test_rejects_disallowed_decision(self):
        gate = self.engine.request_gate(
            run_id="run", kind="k", title="t", prompt="p",
            allowed_decisions=(HumanDecisionType.APPROVE,),
        )
        with self.assertRaises(ApprovalError):
            self.engine.resolve_gate(
                gate_id=gate.gate_id, decision=HumanDecisionType.REJECT, feedback="no"
            )
        self.assertEqual(self.engine.get_gate(gate.gate_id).status, GateStatus.OPEN)

    def test_duplicate_resolution_is_rejected(self):
        gate = self.engine.request_gate(run_id="run", kind="k", title="t", prompt="p")
        self.engine.resolve_gate(
            gate_id=gate.gate_id, decision=HumanDecisionType.APPROVE, feedback="ok"
        )
        with self.assertRaises(ApprovalError):
            self.engine.resolve_gate(
                gate_id=gate.gate_id, decision=HumanDecisionType.REJECT, feedback="late"
            )
        self.assertEqual(len(self.engine.get_decision_history(gate.gate_id)), 1)

    def test_cancelled_gate_cannot_be_resolved(self):
        gate = self.engine.request_gate(run_id="run", kind="k", title="t", prompt="p")
        cancelled = self.engine.cancel_gate(gate.gate_id)
        self.assertEqual(cancelled.status, GateStatus.CANCELLED)
        with self.assertRaises(ApprovalError):
            self.engine.resolve_gate(
                gate_id=gate.gate_id, decision=HumanDecisionType.APPROVE, feedback="late"
            )

    def test_gate_snapshot_is_defensive(self):
        gate = self.engine.request_gate(
            run_id="run", kind="k", title="t", prompt="p", context={"nested": {"a": 1}}
        )
        snapshot = self.engine.get_gate(gate.gate_id)
        snapshot.context["new"] = 2
        self.assertNotIn("new", self.engine.get_gate(gate.gate_id).context)

    def test_concurrent_resolution_allows_only_one_winner(self):
        gate = self.engine.request_gate(run_id="run", kind="k", title="t", prompt="p")
        results = []
        errors = []

        def resolve():
            try:
                results.append(
                    self.engine.resolve_gate(
                        gate_id=gate.gate_id,
                        decision=HumanDecisionType.APPROVE,
                        feedback="race",
                    )
                )
            except ApprovalError:
                errors.append(True)

        threads = [threading.Thread(target=resolve) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 7)
        self.assertEqual(len(self.engine.get_decision_history(gate.gate_id)), 1)


if __name__ == "__main__":
    unittest.main()
