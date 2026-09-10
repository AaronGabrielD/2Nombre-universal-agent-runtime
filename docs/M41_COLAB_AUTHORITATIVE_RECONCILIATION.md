# M41 — Colab authoritative execution reconciliation

M41 connects the provider-neutral M39 `ExecutionReconciler` contract to the existing Colab execution service.

The Colab service now persists each accepted execution result as JSON evidence beneath `.execution-evidence/` inside the configured artifact root. Evidence writes are atomic and contain result metadata only; executable source code is not persisted.

An authenticated `GET /executions/<execution_id>` endpoint returns the persisted result. A missing execution returns `404` and does not authorize retry by itself.

`ColabExecutionReconciler` is the provider adapter used by M39. It treats a missing execution as no authoritative result, validates the returned execution identifier and result structure, and leaves the runtime responsible for deciding whether reconciliation may change workflow state.

This is still dependent on the lifetime of the configured Colab artifact storage. A Colab VM restart or storage reset can remove evidence; M41 therefore does not claim durable cross-VM execution history.
