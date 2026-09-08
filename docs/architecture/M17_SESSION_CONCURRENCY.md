# M17 — Session Concurrency Hardening

M17 serializes all mutable `SessionManager` operations with a process-local reentrant lock and keeps snapshots isolated through deep copies.

## Why

M15 intentionally executed workers sequentially because the previous session layer exposed mutable records without one manager-wide mutation lock. That was safe but prevented controlled parallelism.

## Guarantees

- concurrent execution-result writes are serialized;
- concurrent worker-output writes do not overwrite one another accidentally;
- snapshots are detached from repository state;
- session lifecycle transitions use the same lock as other mutations;
- the repository interface remains provider-neutral.

## Scope

This is process-local concurrency protection. It does not provide distributed locking across multiple service replicas. A persistent production store with transactional semantics is still required before scaling horizontally.
