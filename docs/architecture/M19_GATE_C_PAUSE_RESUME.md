# M19 Gate C pause/resume verification

M19 requires the integrated orchestrator to stop before worker planning/execution when a worker requests a high-risk or approval-required tool. The run enters `WORKER_WAITING_HUMAN` and returns the exact Gate C and worker identifiers.

After a human decision, `resume_after_tool_gate()` verifies the run, gate, and worker binding. Approval returns the run to `EXECUTING`; rejection moves it to `REVISION`. Repeated authorization requests reuse an existing Gate C instead of creating duplicate approvals.
