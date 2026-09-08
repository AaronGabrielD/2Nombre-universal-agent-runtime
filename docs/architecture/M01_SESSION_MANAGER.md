# M01 — Session Manager

## Boundary

M01 owns the lifecycle and isolation of one runtime execution identified by `run_id`.
It stores session-scoped messages, artifacts, human decisions, worker outputs, execution results, the architecture plan, and the final result.

M01 does not decide solutions, call Gemini, create agents, execute code, or render UI.

## Public API

`SessionManager` provides:

- `create_session()` — creates a unique `run_id` in `IDLE`.
- `destroy_session(run_id)` — removes a session.
- `get_context(run_id)` — reads the `RunContext`.
- `transition(run_id, target)` — delegates legal state transitions to M00.
- `add_message(...)` — stores user/agent messages in the session.
- `add_artifact(...)` — attaches an `ArtifactRef` to the session.
- `add_decision(...)` — records a human decision and enforces `run_id` ownership.
- `add_execution_result(...)` — stores an execution result.
- `set_architecture_plan(...)` — stores the approved/planned architecture object.
- `set_worker_output(...)` — stores output for a specific worker and enforces `run_id` ownership.
- `set_final_result(...)` — stores the final result and enforces `run_id` ownership.
- `snapshot(run_id)` — exposes the session record to higher orchestration layers.

## Storage policy

The first implementation uses a thread-safe in-memory repository. This is intentional: persistence is an adapter concern and can be replaced without changing the `SessionManager` public API.

Later persistence may use SQLite/PostgreSQL/another store behind the same repository boundary.

## Isolation rules

1. Every mutable record is reachable through one `run_id`.
2. Cross-run decisions, worker outputs, and final results are rejected.
3. Unknown `run_id` values raise `SessionNotFoundError`.
4. State transition legality remains centralized in M00's state machine.
5. Secrets must never be stored in messages, metadata, or logs unless a future explicit secret-storage module is introduced.

## Acceptance criteria

- Unique session IDs are generated automatically.
- Two sessions cannot see each other's messages or artifacts.
- Illegal state transitions are rejected.
- Cross-run records are rejected.
- Destroyed sessions cannot be read.
- Tests cover creation, isolation, transitions, cross-run rejection, deletion, and validation.
