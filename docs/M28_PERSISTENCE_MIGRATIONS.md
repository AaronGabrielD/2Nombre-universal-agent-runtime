# M28 — Schema-versioned persistence and durable backend boundary

M28 adds two pieces that were intentionally deferred:

1. `MigrationRunner` provides ordered, transactional SQLite schema migrations.
2. `JsonFileSessionRepository` provides a durable, dependency-free backend implementing the existing `SessionRepository` contract.

## Migration contract

Each migration has an integer version, a stable name, and an `apply(connection)` callback. Applied versions are stored in `schema_migrations`. A migration runs once, in order, and rolls back on failure.

## JSON session backend

Each run is stored as one JSON document with an explicit `schema_version`. Writes use a temporary file followed by atomic replacement, reducing the chance of a partially written session record.

The backend reconstructs runtime domain objects explicitly rather than deserializing arbitrary Python objects. It is therefore a safer portable interchange format than the trusted-storage-only pickle used by the legacy SQLite session repository.

## Scope

`JsonFileSessionRepository` is intended for single-process or low-contention durable deployments. It is not a replacement for a transactional shared database in a multi-instance deployment.

The `SessionRepository` protocol remains the stable integration boundary, so a future Postgres, Redis-backed, or hosted repository can be introduced without changing M01 callers.
