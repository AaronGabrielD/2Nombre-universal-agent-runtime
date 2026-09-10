# A2 — Session Persistence Hardening Audit

## Audit baseline

- Repository: `AaronGabrielD/2Nombre-universal-agent-runtime`
- Branch audited: `main`
- Current main commit verified during final audit: `f748cffff3fdd749d89a3c3ae913b7dfb9d7425e`
- Current main commit message: `test: harden A2 session persistence coverage`
- Audit branch: `audit/A2_SESSION_PERSISTENCE_HARDENING_CURRENT`
- Production files modified by this delegated task: **none**
- Integration status: **not integrated by this task**

## Method and execution limits

The audit was performed against the actual GitHub `main` tree and relevant commit diffs. The repository was not available as a local checkout in the execution environment, so the project test suite was **not executed by this audit agent**. No CI workflow run was available for the audited `main` commit at the time of the initial check; therefore this report does not claim a passing CI result.

`main` changed while the audit was in progress. The initial inspected commit was `00777ce5d228de1dd4bb59bbdb07fbede2f5434a`; a later verified `main` HEAD is `f748cffff3fdd749d89a3c3ae913b7dfb9d7425e`. The final conclusions below are based on the **current HEAD**, not the stale initial snapshot.

## Executive result

**RESULT: BLOCKED**

Current `main` already contains meaningful A2 hardening: JSON filename/payload `run_id` binding is implemented, reconstructed JSON sessions are passed through an integrity validator, SQLite decoded sessions are validated after unpickling, JSON malformed top-level/record/context containers are partially guarded, and dedicated durability/integrity tests now exist. fileciteturn55file0L2 fileciteturn62file0L2 fileciteturn69file0L2

However, three material defects remain and block a fully hardened A2 result:

1. SQLite does not bind the database row key to `record.context.run_id`.
2. SQLite malformed pickled `SessionRecord` state can still escape the repository error boundary through unchecked attribute access before validation completes.
3. The in-memory repository still exposes live mutable records and retains caller-owned references.

A fourth consistency defect is also present: SQLite `create()`/`save()` do not run the same session integrity validation that JSON writes now run. This permits invalid state to be persisted and only rejected later during read/restart.

## Findings

### A2-01 — SQLite row key and payload `run_id` are not bound

- Classification: **FAILURE**
- File: `app/session/repository.py`
- Location: `SQLiteSessionRepository.get()`, `list()`, `_decode()`
- Severity: **HIGH**

**Observed behavior**

The SQLite table has a `run_id` primary-key column plus a payload containing a second copy of the run identity. `_decode(run_id, payload)` validates the decoded type and then calls `validate_session_record_integrity(record)`, but it never compares `record.context.run_id` with the row key passed as `run_id`. Consequently a row keyed as `run-a` can contain a valid `SessionRecord` for `run-b` and still be returned as the result of `get("run-a")`.

**Evidence**

The current decoder receives the row ID but does not compare it to the decoded record identity. fileciteturn60file0L2 The current integrity helper checks the embedded `SessionRecord` structure and child ownership, but no storage-key binding is present there either. fileciteturn62file0L2

**Impact**

A corrupted or inconsistent SQLite row can be exposed as a different logical run. That violates the session isolation invariant even when the embedded record itself passes all other validation checks.

**Recommendation**

After decoding and integrity validation, require `record.context.run_id == run_id`; otherwise raise `SessionRepositoryError`. Apply the same rule for rows returned by `list()`.

---

### A2-02 — SQLite malformed `SessionRecord` can escape as a non-repository exception

- Classification: **FAILURE**
- File: `app/session/repository.py`
- Location: `validate_session_record_integrity()` and `_decode()`
- Severity: **MEDIUM**

**Observed behavior**

The integrity helper starts with `isinstance(record, SessionRecord)` and then immediately evaluates `record.context.run_id`. A pickled `SessionRecord` with `context=None`, or another invalid object assigned to `context`, can therefore raise `AttributeError` before the helper can translate the condition to `SessionRepositoryError`. `_decode()` catches only the exceptions raised directly by `pickle.loads()`; it does not catch `AttributeError` from the subsequent integrity helper.

The JSON loader has stronger shape checks because it explicitly rejects non-dictionary `context` before accessing its keys, but SQLite uses Python object deserialization and must defend the same logical boundary.

**Evidence**

The helper accesses `record.context.run_id` immediately after the outer record type check, and `_decode()` only wraps `SessionRepositoryError` after calling the helper. fileciteturn62file0L2

**Impact**

Malformed trusted-storage data does not consistently fail closed through the repository's declared `SessionRepositoryError` interface.

**Recommendation**

Validate `record.context` type before dereferencing it and ensure all integrity failures are converted to `SessionRepositoryError`. Keep the explicit trusted-storage boundary for pickle; this is not a claim that attacker-controlled SQLite files are safe.

---

### A2-03 — SQLite writes do not enforce the same integrity validation as JSON writes

- Classification: **FAILURE**
- File: `app/session/repository.py`
- Location: `SQLiteSessionRepository.create()` and `save()`
- Severity: **MEDIUM**

**Observed behavior**

JSON `_write()` currently calls `validate_session_record_integrity(record)` before publication. SQLite `create()` and `save()` serialize and write `record` without calling the integrity validator. This means invalid child associations, invalid contract fields, or other structurally inconsistent session state can be committed to SQLite and only rejected when a later read invokes `_decode()`.

**Evidence**

JSON explicitly validates before serialization in `_write()`. fileciteturn55file0L2 SQLite `create()` and `save()` currently pickle the record directly and write it without the validation helper. fileciteturn62file0L2

**Impact**

The two durable providers have inconsistent write contracts. SQLite can persist state that JSON refuses, increasing the chance of delayed restart failures and making behavior provider-dependent.

**Recommendation**

Run the existing integrity validator before SQLite create/save, preferably against a detached copy, and keep the same fail-closed error boundary for both durable providers.

---

### A2-04 — In-memory repository exposes live mutable session state

- Classification: **FAILURE**
- File: `app/session/repository.py`
- Location: `InMemorySessionRepository.create()`, `get()`, `save()`
- Severity: **MEDIUM**

**Observed behavior**

`create()` stores the caller's `SessionRecord` directly, `get()` returns the stored object directly, and `save()` stores the caller's object directly. `list()` is defensive, but the main repository operations are not.

This permits callers holding a returned or previously supplied object to mutate session state without crossing the explicit repository save boundary. The risk is material for `RunContext.metadata`, `SessionMessage.metadata`, `WorkerOutput.output`, and `FinalResult` nested dictionaries.

**Evidence**

The current implementation stores and returns direct object references for create/get/save, while only `list()` deep-copies records. fileciteturn62file0L2 Existing tests cover manager thread serialization and cross-run execution-result containment, but they do not cover repository aliasing. fileciteturn69file0L2

**Impact**

The process-local provider does not provide the same defensive isolation semantics as the durable providers. Direct repository use can bypass intended mutation boundaries.

**Recommendation**

Adopt copy-on-write/copy-on-read for `create()`, `get()`, and `save()`. Validate the detached value before replacing the stored state.

---

### A2-05 — JSON malformed nested container handling remains incomplete

- Classification: **FAILURE**
- File: `app/session/json_repository.py`
- Location: `_from_dict()` plus `get()`/`list()` exception boundary
- Severity: **MEDIUM**

**Observed behavior**

The current JSON decoder rejects non-object top-level JSON, non-object `record`, and non-object `context`, which is an improvement. However it still assumes several nested shapes. For example, if `worker_outputs` is a JSON list, `_from_dict()` executes `raw.get("worker_outputs", {}).items()` and can raise `AttributeError`. `get()` does not catch `AttributeError`.

**Evidence**

The current decoder validates only the top-level, record, and context mapping shapes before later direct `.get()`/`.items()` operations. fileciteturn55file0L2 The existing durability tests cover malformed JSON, invalid execution status, and cross-run messages, but not the `worker_outputs` container case. fileciteturn69file0L2

**Impact**

A malformed persisted JSON file can still escape the repository's typed corruption boundary through an implementation-specific Python exception.

**Recommendation**

Validate every collection/container shape before iteration or `.items()`/indexing, then convert every reconstruction failure to `SessionRepositoryError`.

---

### A2-06 — JSON atomic publication is present; stronger crash durability is optional hardening

- Classification: **VERIFIED**
- File: `app/session/json_repository.py`
- Location: `_write()`
- Severity: **NONE / positive control**

**Observed behavior**

The JSON backend writes to a sibling temporary file and publishes it with `os.replace()`, rather than truncating the final document in place.

**Evidence**

The current `_write()` performs `temp.write_text(...)` followed by `os.replace(temp, path)`. fileciteturn55file0L2 Existing tests assert the final schema and absence of the temporary file after a successful write. fileciteturn65file0L2

**Assessment**

This is a correct basic atomic-publication pattern within the documented backend scope. It does not by itself guarantee crash durability across power loss because there is no explicit file `fsync()` before replacement.

**Recommendation**

Use a unique temporary file per write and `flush()+os.fsync()` before `os.replace()` as optional hardening. Do not characterize JSON as a transactional multi-process store.

---

### A2-07 — JSON storage-key identity binding is now implemented

- Classification: **VERIFIED**
- File: `app/session/json_repository.py`
- Location: `get()`, `list()`, `_from_dict()`
- Severity: **NONE / positive control**

**Observed behavior**

The current JSON implementation passes the requested/file-derived run ID into `_from_dict()` and rejects a payload whose `context.run_id` does not match that expected ID.

**Evidence**

`get()` calls `_from_dict(..., expected_run_id=run_id)` and `list()` calls `_from_dict(..., expected_run_id=path.stem)`. `_from_dict()` explicitly compares the decoded context ID to the expected storage ID. fileciteturn55file0L2

**Assessment**

The original JSON cross-run identity defect is fixed on current `main`.

---

### A2-08 — JSON/SQLite decoded-session integrity validation is now present but incomplete

- Classification: **VERIFIED** for covered fields; **NOT VERIFIED** as a complete invariant proof
- Files: `app/session/repository.py`, `app/session/json_repository.py`
- Location: `validate_session_record_integrity()` and JSON `_from_dict()`
- Severity: **MEDIUM**

**Observed behavior**

Current `main` validates child ownership for messages, decisions, worker outputs, and final results; validates `ArtifactRef`, `ExecutionResult`, `HumanDecision`, `ArchitecturePlan`, and `FinalResult`; and runs the helper for SQLite decode and JSON reconstruction. fileciteturn62file0L2 fileciteturn55file0L2

The validator does not yet prove every declared `RunContext` shape before dereferencing it, and SQLite row identity is not included in the validation.

**Recommendation**

Keep the existing helper, extend its guards for `context` and bind it to the storage key when called from SQLite.

---

### A2-09 — Concurrency is protected within one manager/repository instance; no multi-process JSON guarantee is asserted

- Classification: **VERIFIED**
- Files: `app/session/manager.py`, `app/session/repository.py`, `app/session/json_repository.py`
- Location: `RLock` usage and current M28 scope
- Severity: **LOW / documented limitation**

**Observed behavior**

`SessionManager` and repository implementations use instance-local `RLock`. Existing main tests exercise concurrent `SessionManager` updates and require all 40 messages to be present. fileciteturn69file0L2

The M28 design boundary describes JSON as intended for single-process or low-contention durable deployments, not as a transactional shared database. fileciteturn36file0L2

**Assessment**

No multi-process guarantee should be inferred. This is a design boundary, not a confirmed defect in the documented one-instance usage model.

---

### A2-10 — SQLite/pickle remains trusted application storage only

- Classification: **VERIFIED / DESIGN LIMITATION**
- File: `app/session/repository.py`
- Location: `SQLiteSessionRepository` docstring and pickle load path
- Severity: **DESIGN LIMITATION**

**Observed behavior**

SQLite persists `SessionRecord` with `pickle` and the code explicitly says the database must be treated as trusted application storage and not as an attacker-controlled file.

**Evidence**

The class documentation and `pickle.loads()` usage establish the current trust model. fileciteturn62file0L2

**Assessment**

This must not be reported as an attacker-safe format. A2 should preserve the stated trusted-storage distinction rather than invent a vulnerability or silently redesign the backend.

---

### A2-11 — Workflow-state and human-approval invariants remain outside persistence hardening

- Classification: **VERIFIED**
- Files: `app/core/states.py`, `app/core/models.py`, `app/runtime/service.py`
- Location: `RunContext.transition_to()`, state table, Gate A/Gate D validation
- Severity: **NONE / positive control**

**Observed behavior**

Persistence does not define or modify workflow transitions. `RunContext.transition_to()` still delegates to the existing `ensure_transition()` mechanism, while `RuntimeCoordinator` still requires resolved, matching approval decisions before applying human-gated transitions. fileciteturn6file0L2 fileciteturn8file0L2 fileciteturn29file0L2

**Assessment**

No persistence change identified in this audit requires altering the state machine or approval gates.

---

### A2-12 — CRUD/restart coverage is materially better, but not execution-verified by this audit agent

- Classification: **NOT VERIFIED**
- Files: `tests/test_session_durability.py`, `tests/test_session_sqlite.py`, `tests/test_m27_m28_persistence.py`
- Severity: **MEDIUM / validation gap**

**Observed behavior**

Current `main` has explicit tests for JSON and SQLite restart with session payloads, corruption handling, cross-run nested JSON records, unsafe JSON run IDs, concurrent manager updates, and missing sessions. fileciteturn69file0L2 Existing SQLite persistence tests also cover repository recreation and mutation persistence. fileciteturn23file0L2

**Assessment**

These tests were inspected but not executed in this audit environment. No passing result is claimed.

## Coverage matrix

| Area | Result | Conclusion |
|---|---|---|
| JSON storage-key vs payload identity | VERIFIED | Current main explicitly checks expected run ID. |
| SQLite storage-key vs payload identity | FAILURE | Row key and embedded `context.run_id` are not compared. |
| JSON top-level/record/context corruption | VERIFIED | Explicit shape checks now exist. |
| JSON nested-shape fail-closed | FAILURE | `worker_outputs` and similar nested assumptions can leak `AttributeError`. |
| JSON contract validation on read/write | VERIFIED | Integrity helper is called on both decode and JSON write. |
| SQLite contract validation on read | VERIFIED | Integrity helper is called after unpickle. |
| SQLite contract validation on write | FAILURE | `create()`/`save()` do not invoke the helper. |
| In-memory defensive isolation | FAILURE | create/get/save expose live mutable references. |
| JSON atomic publication | VERIFIED | Temp file + `os.replace()` present. |
| JSON crash-durability beyond atomic publication | NOT VERIFIED | No `fsync()` path reviewed as executed behavior. |
| Concurrent manager updates | VERIFIED by existing test presence; execution not verified here | `RLock` serializes manager operations. |
| Multi-process JSON transactionality | NOT APPLICABLE | Not a documented guarantee. |
| SQLite/pickle attacker-controlled storage safety | NOT APPLICABLE | Explicitly outside the trust model. |
| Workflow-state machine preservation | VERIFIED | Persistence hardening does not alter transitions. |
| Human-in-the-loop preservation | VERIFIED | Gate validation remains in coordinator. |
| Restart durability | NOT VERIFIED in this environment | Existing tests are present but were not executed here. |

## Required remediation before A2 acceptance

1. Bind SQLite row ID to `SessionRecord.context.run_id` during decode/list.
2. Make SQLite integrity validation safe against malformed `record.context` and map all decode-integrity failures to `SessionRepositoryError`.
3. Validate SQLite records before create/save, matching JSON behavior.
4. Make `InMemorySessionRepository` defensive on create/get/save.
5. Complete JSON nested container validation and ensure all malformed data stays inside the `SessionRepositoryError` boundary.
6. Add focused tests for each item above and run the complete project suite after integration.

## Explicit non-goals

- No new persistence backend.
- No new workflow state or phase.
- No change to Gate A, Gate C, or Gate D.
- No automatic recovery or replay.
- No change to the SQLite trusted-storage assumption.
- No multi-process transaction guarantee for JSON.
- No direct modification of production files by this delegated task.

## Final conclusion

Current `main` is materially stronger than the initial A2 baseline and has already integrated part of the intended hardening. It is **not yet fully acceptable for A2** because the residual SQLite identity/error-boundary problems, SQLite write-validation asymmetry, and in-memory aliasing remain real correctness/integrity issues. The candidate hardening package should therefore be treated as **BLOCKED pending integration and execution of the focused regressions and full project suite**.
