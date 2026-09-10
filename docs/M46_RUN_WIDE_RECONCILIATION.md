# M46 — Run-wide execution reconciliation

## Goal

Provide one provider-neutral service that inspects or explicitly reconciles every latest durable execution lease belonging to a run.

## Scope

- Enumerate the latest persisted lease for each task.
- Produce deterministic ordering by worker, task, and idempotency key.
- Inspect local durable evidence without contacting any backend.
- Explicitly delegate backend reconciliation only when the caller invokes `reconcile_backend()`.
- Reuse the existing `ExecutionReconciliationService` contract and backend authority rules.
- Never execute code, create a new lease, or authorize a retry.

## API

`RunExecutionReconciliationService.inspect(run_id)` returns a `RunReconciliation` containing one `ExecutionReconciliation` item per latest persisted lease.

`RunExecutionReconciliationService.reconcile_backend(run_id)` explicitly permits the configured `ExecutionReconciler` to provide authoritative evidence for entries that still need backend checking.

`RunReconciliation.terminal` contains completed/failed entries. `RunReconciliation.pending` contains entries whose authoritative state remains unresolved.

## Safety properties

1. Existing local execution evidence is preferred and prevents another backend lookup for that execution.
2. Missing local evidence never becomes an implicit retry.
3. Backend authority is invoked only through an explicit reconciliation method.
4. Deterministic ordering makes multi-task recovery reproducible and auditable.
5. The service has no execution-backend dependency and cannot submit fresh code.

## Tests

`tests/test_m46_reconciliation_batch.py` covers deterministic enumeration, local-evidence short-circuiting, authoritative result persistence, and fail-closed behavior when no backend authority is configured.
