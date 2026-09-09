# M21 — Persistent Session Storage

M21 extends the existing `SessionRepository` boundary with a SQLite implementation and wires `SessionManager` mutations through `repository.save()`.

## Design

- The runtime keeps `InMemorySessionRepository` as the default, preserving lightweight/test usage.
- `SQLiteSessionRepository` uses only the Python standard library.
- `SessionManager` remains the owner of lifecycle and concurrency; repositories own storage.
- Re-opening a repository against the same database restores the complete `SessionRecord`, including context, messages, artifacts, decisions, execution results, worker outputs, architecture plan, and final result.
- The persistent implementation is intentionally provider-agnostic and suitable for a Colab-mounted database file.

## Trust boundary

Session records are serialized with Python pickle for compact, dependency-free persistence. The SQLite file must therefore be treated as trusted application storage and must not be loaded from an untrusted source.

A future production-hardening milestone can replace serialization with a versioned JSON schema or normalized tables without changing the `SessionRepository` contract used by M01.
