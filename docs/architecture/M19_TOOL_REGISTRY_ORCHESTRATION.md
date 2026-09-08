# M19 — Tool Registry + Orchestration

## Purpose

M19 integrates M07 tool/capability resolution and M16 tool authorization into M15 Integrated Orchestrator.

Workers may declare `required_tools`. The orchestrator must resolve those requirements before requesting an execution plan or execution.

## Safety invariants

- Unknown or unavailable tools/capabilities fail closed.
- Workers with no tool requirements continue through the normal Gate-A execution path.
- Low-risk tools are resolved by M07/M16 without opening a human gate.
- High-risk or explicitly approval-required tools open Gate C (`TOOL_RISK`).
- Gate C is bound to both `run_id` and `worker_id` and cannot be resolved for another worker.
- The orchestrator transitions to `WORKER_WAITING_HUMAN` before CrewAI planning or M08 execution for the gated worker.
- A repeated orchestration pass reuses the same open/resolved Gate C instead of creating duplicates.
- Gate-C approval is used as the execution authorization for a worker whose risky tool access was approved; Gate A remains a prerequisite because the run must already be in `EXECUTING`.
- Gate-C rejection moves the run to `REVISION` without backend execution.
- Tool registrations remain declarative. M07 does not invoke handlers, and M14 does not receive live tool handlers.

## Pause / resume lifecycle

```text
EXECUTING
   |
   | worker declares risky tool
   v
M07 validate requirements
   |
   v
M16 request authorization
   |
   v
Gate C OPEN
   |
   v
WORKER_WAITING_HUMAN
   |                 |
 APPROVE          REJECT
   |                 |
   v                 v
EXECUTING         REVISION
   |
   v
CrewAI plan -> M13 -> M08
```

The public resume operation is `IntegratedOrchestrator.resume_after_tool_gate(...)`. It validates the paused lifecycle, resolves Gate C through M16, and only then returns to execution.

## Idempotency

M16 now searches the approval engine for a matching `TOOL_RISK` gate using worker identity and requested risky-tool/capability context. An open gate is reused; a resolved gate reuses its recorded decision. This prevents duplicate Gate-C records when a paused run is resumed.

## Scope

M19 is still an authorization/policy layer. The current CrewAI adapter is deliberately tool-less and generated worker code is still executed only by the M08 boundary. A future milestone can add real tool invocation adapters while preserving this same authorization contract.
