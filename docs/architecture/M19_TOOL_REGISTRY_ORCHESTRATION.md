# M19 — Tool Registry + Orchestration

M19 integrates M07 tool/capability resolution and M16 authorization into M15. Unknown or unavailable requirements fail closed. Risky or approval-required tools open Gate C, pause the run before worker planning/execution, and bind approval to both `run_id` and `worker_id`.

A paused run enters `WORKER_WAITING_HUMAN`. Approval resumes the exact worker; rejection moves the run to `REVISION`. Repeated authorization requests reuse matching open/resolved Gate-C records rather than creating duplicates.
