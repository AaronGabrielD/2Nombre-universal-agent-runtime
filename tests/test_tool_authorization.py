import unittest

from app.approval.service import HumanApprovalEngine
from app.core.contracts import HumanDecisionType, RiskLevel
from app.tools import CapabilitySpec, ToolAuthorizationError, ToolAuthorizationRequest, ToolAuthorizationService, ToolRegistration, ToolRegistry


def safe_handler(_payload):
    raise AssertionError("tool handler must never be called by authorization service")


class ToolAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.approvals = HumanApprovalEngine()
        self.registry.register_capability(CapabilitySpec("files", "Files", "file access"))
        self.registry.register_tool(ToolRegistration(
            tool_id="safe", name="Safe", description="safe tool", handler=safe_handler, capabilities=("files",)
        ))
        self.registry.register_tool(ToolRegistration(
            tool_id="risky", name="Risky", description="risky tool", handler=safe_handler,
            risk_level=RiskLevel.HIGH, requires_human_approval=True, capabilities=("files",)
        ))
        self.service = ToolAuthorizationService(registry=self.registry, approvals=self.approvals)

    def test_safe_tool_gets_authorization_without_gate(self):
        decision = self.service.request_authorization(
            ToolAuthorizationRequest("run-1", "worker-1", required_tools=("safe",))
        )
        self.assertIsNone(decision.gate_id)
        self.assertTrue(decision.authorization.authorized)
        self.assertEqual(self.approvals.list_open_gates(run_id="run-1"), ())

    def test_risky_tool_requires_gate_c(self):
        decision = self.service.request_authorization(
            ToolAuthorizationRequest("run-1", "worker-1", required_tools=("risky",))
        )
        self.assertIsNotNone(decision.gate_id)
        self.assertIsNone(decision.authorization)
        gate = self.approvals.get_gate(decision.gate_id)
        self.assertEqual(gate.kind, "TOOL_RISK")

    def test_gate_c_approval_authorizes_execution(self):
        decision = self.service.request_authorization(
            ToolAuthorizationRequest("run-1", "worker-1", required_tools=("risky",))
        )
        authorization = self.service.resolve_gate(
            gate_id=decision.gate_id,
            decision=HumanDecisionType.APPROVE,
            run_id="run-1",
            worker_id="worker-1",
            feedback="Approved.",
        )
        self.assertTrue(authorization.authorized)
        self.assertEqual(authorization.gate_id, decision.gate_id)

    def test_gate_c_rejection_fails_closed(self):
        decision = self.service.request_authorization(
            ToolAuthorizationRequest("run-1", "worker-1", required_tools=("risky",))
        )
        authorization = self.service.resolve_gate(
            gate_id=decision.gate_id,
            decision=HumanDecisionType.REJECT,
            run_id="run-1",
            worker_id="worker-1",
            feedback="No.",
        )
        self.assertFalse(authorization.authorized)

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ToolAuthorizationError):
            self.service.request_authorization(
                ToolAuthorizationRequest("run-1", "worker-1", required_tools=("missing",))
            )


if __name__ == "__main__":
    unittest.main()
