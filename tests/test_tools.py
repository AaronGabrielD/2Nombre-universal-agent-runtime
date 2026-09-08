from __future__ import annotations

import unittest

from app.core.contracts import RiskLevel
from app.tools import CapabilitySpec, ToolRegistration, ToolRegistry, ToolRegistryError


def _handler(payload):
    return {"ok": True, "payload": payload}


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_capability(
        CapabilitySpec(
            "filesystem.read",
            "Filesystem Read",
            "Read files from an approved source.",
        )
    )
    registry.register_capability(
        CapabilitySpec(
            "text.transform",
            "Text Transform",
            "Transform user-provided text.",
        )
    )
    registry.register_tool(
        ToolRegistration(
            tool_id="file_reader",
            name="File Reader",
            description="Reads an approved file.",
            handler=_handler,
            capabilities=("filesystem.read",),
        )
    )
    registry.register_tool(
        ToolRegistration(
            tool_id="text_transformer",
            name="Text Transformer",
            description="Transforms text.",
            handler=_handler,
            capabilities=("text.transform",),
            available=False,
        )
    )
    return registry


class ToolRegistryTests(unittest.TestCase):
    def test_register_and_get_tool_without_execution(self):
        registry = _registry()
        called = False

        def forbidden(_payload):
            nonlocal called
            called = True
            return None

        registry.register_tool(
            ToolRegistration(
                tool_id="safe_test",
                name="Safe Test",
                description="A non-executed test tool.",
                handler=forbidden,
                capabilities=("text.transform",),
            )
        )

        resolved = registry.get_tool("safe_test", require_available=True)
        self.assertEqual(resolved.tool_id, "safe_test")
        self.assertFalse(called)

    def test_duplicate_ids_are_rejected(self):
        registry = _registry()
        with self.assertRaisesRegex(ToolRegistryError, "tool already registered"):
            registry.register_tool(
                ToolRegistration(
                    tool_id="file_reader",
                    name="Duplicate",
                    description="Duplicate.",
                    handler=_handler,
                    capabilities=("filesystem.read",),
                )
            )

    def test_tool_cannot_reference_unknown_capability(self):
        registry = ToolRegistry()
        with self.assertRaisesRegex(ToolRegistryError, "unregistered capabilities"):
            registry.register_tool(
                ToolRegistration(
                    tool_id="unknown_capability_tool",
                    name="Unknown",
                    description="Unknown capability.",
                    handler=_handler,
                    capabilities=("does.not.exist",),
                )
            )

    def test_high_risk_tool_requires_human_approval(self):
        with self.assertRaisesRegex(
            ValueError, "high-risk tools must require human approval"
        ):
            ToolRegistration(
                tool_id="dangerous",
                name="Dangerous",
                description="Dangerous tool.",
                handler=_handler,
                risk_level=RiskLevel.HIGH,
                requires_human_approval=False,
            ).validate()

    def test_unavailable_tool_is_not_resolved_when_availability_is_required(self):
        registry = _registry()
        with self.assertRaisesRegex(ToolRegistryError, "tool is unavailable"):
            registry.get_tool("text_transformer", require_available=True)

        result = registry.validate_requirements(required_tools=("text_transformer",))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.missing_tools, ("text_transformer",))

    def test_capability_queries_fail_closed_and_filter_available_tools(self):
        registry = _registry()
        self.assertEqual(
            tuple(
                tool.tool_id
                for tool in registry.tools_for_capabilities(("filesystem.read",))
            ),
            ("file_reader",),
        )
        with self.assertRaisesRegex(ToolRegistryError, "unknown capabilities"):
            registry.tools_for_capabilities(("missing",))

    def test_snapshots_are_detached_from_registry_state(self):
        registry = ToolRegistry()
        registry.register_capability(
            CapabilitySpec("demo", "Demo", "Demonstration capability.")
        )
        original_metadata = {"nested": {"enabled": True}}
        registry.register_tool(
            ToolRegistration(
                tool_id="demo_tool",
                name="Demo",
                description="Demo tool.",
                handler=_handler,
                capabilities=("demo",),
                metadata=original_metadata,
            )
        )

        snapshot = registry.get_tool("demo_tool")
        snapshot.metadata["nested"]["enabled"] = False
        snapshot.input_schema["changed"] = True

        fresh = registry.get_tool("demo_tool")
        self.assertEqual(fresh.metadata, {"nested": {"enabled": True}})
        self.assertNotIn("changed", fresh.input_schema)


if __name__ == "__main__":
    unittest.main()
