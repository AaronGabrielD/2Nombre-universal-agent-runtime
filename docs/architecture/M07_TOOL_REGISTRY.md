# M07 — Tool Registry & Capability Registry

## Purpose

M07 defines the explicit catalog of capabilities and concrete tools available to the runtime. It is a declarative boundary: registration and resolution describe what exists, but do not execute anything.

## Responsibilities

- Register unique capability identifiers and descriptions.
- Register unique tools with handler references, schemas, risk metadata, availability, and capability membership.
- Reject high-risk tools that do not require human approval.
- Reject tools that reference capabilities not registered in the runtime.
- Resolve requested tools and capabilities deterministically.
- Fail closed for unknown or unavailable requirements.
- Return detached metadata snapshots so callers cannot mutate registry state accidentally.

## Explicit non-responsibilities

M07 does not execute handlers, call Gemini, create workers, display UI, approve actions, or choose an execution backend. Those concerns belong to other milestones, especially M08 Execution Gateway.

## Runtime boundary

```text
M04 Architect / M06 Workers
          |
          | required_tools / required_capabilities
          v
   +-------------------+
   |       M07         |
   | Tool + Capability |
   |      Registry     |
   +-------------------+
          |
          | resolved registrations
          v
        M08
   Execution Gateway
          |
          v
      Tool Handler
```

The handler is stored as a callable reference only. M07 never calls it.

## Safety invariants

1. IDs are unique within their registry namespace.
2. A tool cannot be registered with an unknown capability.
3. A high-risk tool must explicitly require human approval.
4. Unavailable tools do not satisfy an availability-constrained resolution.
5. Unknown requirements produce a failed resolution rather than an invented capability.
6. Registry reads return detached schema/metadata snapshots.

## Example

```python
registry.register_capability(
    CapabilitySpec(
        capability_id="filesystem.read",
        name="Filesystem Read",
        description="Read files from an approved source.",
    )
)

registry.register_tool(
    ToolRegistration(
        tool_id="file_reader",
        name="File Reader",
        description="Reads an approved file.",
        handler=file_reader_handler,
        capabilities=("filesystem.read",),
        risk_level=RiskLevel.LOW,
    )
)

result = registry.validate_requirements(
    required_tools=("file_reader",),
    required_capabilities=("filesystem.read",),
)
```

`result.is_valid` must be true before a later execution layer is allowed to consider the tool. M08 is responsible for the actual authorization/approval check immediately before execution.
