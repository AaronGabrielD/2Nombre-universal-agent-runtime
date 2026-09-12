from __future__ import annotations
import unittest
from app.core.contracts import RiskLevel
from app.tools import CapabilitySpec,ToolRegistration,ToolRegistry,ToolRegistryError
def _handler(payload):return {"ok":True,"payload":payload}
def _registry():
    r=ToolRegistry();r.register_capability(CapabilitySpec("filesystem.read","Filesystem Read","Read files."));r.register_capability(CapabilitySpec("text.transform","Text Transform","Transform text."));r.register_tool(ToolRegistration("file_reader","File Reader","Reads files.",handler=_handler,capabilities=("filesystem.read",)));r.register_tool(ToolRegistration("text_transformer","Text Transformer","Transforms text.",handler=_handler,capabilities=("text.transform",),available=False));return r
class ToolRegistryTests(unittest.TestCase):
    def test_register_and_get_tool_without_execution(self):
        r=_registry();called=False
        def forbidden(_):
            nonlocal called;called=True
        r.register_tool(ToolRegistration("safe_test","Safe Test","Test",handler=forbidden,capabilities=("text.transform",)));self.assertEqual(r.get_tool("safe_test",require_available=True).tool_id,"safe_test");self.assertFalse(called)
    def test_duplicate_ids_are_rejected(self):
        with self.assertRaisesRegex(ToolRegistryError,"tool already registered"): _registry().register_tool(ToolRegistration("file_reader","Duplicate","Duplicate",handler=_handler,capabilities=("filesystem.read",)))
    def test_tool_cannot_reference_unknown_capability(self):
        r=ToolRegistry()
        with self.assertRaisesRegex(ToolRegistryError,"unregistered capabilities"):r.register_tool(ToolRegistration("unknown","Unknown","Unknown",handler=_handler,capabilities=("does.not.exist",)))
    def test_high_risk_tool_requires_human_approval(self):
        with self.assertRaisesRegex(ValueError,"high-risk tools must require human approval"):ToolRegistration("dangerous","Dangerous","Dangerous",handler=_handler,risk_level=RiskLevel.HIGH,requires_human_approval=False).validate()
    def test_unavailable_tool_is_not_resolved_when_availability_is_required(self):
        r=_registry();
        with self.assertRaisesRegex(ToolRegistryError,"tool is unavailable"):r.get_tool("text_transformer",require_available=True)
        result=r.validate_requirements(required_tools=("text_transformer",));self.assertFalse(result.is_valid);self.assertEqual(result.missing_tools,("text_transformer",))
    def test_capability_queries_fail_closed_and_filter_available_tools(self):
        r=_registry();self.assertEqual(tuple(t.tool_id for t in r.tools_for_capabilities(("filesystem.read",))), ("file_reader",))
        with self.assertRaisesRegex(ToolRegistryError,"unknown capabilities"):r.tools_for_capabilities(("missing",))
    def test_snapshots_are_detached_from_registry_state(self):
        r=ToolRegistry();r.register_capability(CapabilitySpec("demo","Demo","Demo"));r.register_tool(ToolRegistration("demo_tool","Demo","Demo",handler=_handler,capabilities=("demo",),metadata={"nested":{"enabled":True}}));s=r.get_tool("demo_tool");s.metadata["nested"]["enabled"]=False;s.input_schema["changed"]=True;fresh=r.get_tool("demo_tool");self.assertEqual(fresh.metadata,{"nested":{"enabled":True}});self.assertNotIn("changed",fresh.input_schema)
    def test_required_capability_must_be_implemented_by_resolved_tool(self):
        r=ToolRegistry();r.register_capability(CapabilitySpec("unimplemented","Unimplemented","Declared but not provided"));result=r.validate_requirements(required_capabilities=("unimplemented",));self.assertFalse(result.is_valid);self.assertEqual(result.missing_capabilities,("unimplemented",));self.assertEqual(result.resolved_tools,())
    def test_distributed_capabilities_are_resolved_across_concrete_tools(self):
        r=ToolRegistry();r.register_capability(CapabilitySpec("a","A","A"));r.register_capability(CapabilitySpec("b","B","B"));r.register_tool(ToolRegistration("tool_a","A","A",handler=_handler,capabilities=("a",)));r.register_tool(ToolRegistration("tool_b","B","B",handler=_handler,capabilities=("b",)));result=r.validate_requirements(required_capabilities=("a","b"));self.assertTrue(result.is_valid);self.assertEqual(tuple(t.tool_id for t in result.resolved_tools),("tool_a","tool_b"))
if __name__=="__main__":unittest.main()
