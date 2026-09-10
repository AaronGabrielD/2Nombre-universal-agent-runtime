# A2 — Proposed Changes for Current `main`

## Baseline

Target current `main` commit: `f748cffff3fdd749d89a3c3ae913b7dfb9d7425e`.

Current main already contains partial A2 hardening: JSON storage-key binding, JSON read validation, SQLite read validation, and expanded restart/corruption/concurrency tests. The proposals below are limited to residual defects found in that current state.

## A2-C01 — Bind SQLite row identity to decoded `SessionRecord`

- **File:** `app/session/repository.py`
- **Problem:** `_decode(run_id, payload)` does not compare the SQLite row key with `record.context.run_id`.
- **Solution:** After unpickling and integrity validation, require `record.context.run_id == run_id`; otherwise raise `SessionRepositoryError`.
- **Reason:** The row key is the storage-level identity and the payload contains a second copy. Both must agree before the record enters the runtime.
- **Side effects:** Existing inconsistent rows become unreadable instead of being silently exposed under the wrong run ID.
- **Tests:** Add get/list tests that inject a valid `SessionRecord` for `run-b` into a SQLite row keyed `run-a` and require `SessionRepositoryError`.

## A2-C02 — Make SQLite integrity validation itself fail closed

- **File:** `app/session/repository.py`
- **Problem:** `validate_session_record_integrity()` dereferences `record.context.run_id` before checking that `context` is a `RunContext`. `_decode()` does not wrap that post-unpickle `AttributeError`.
- **Solution:** Check `record.context` type before dereferencing it. Keep all integrity failures inside `SessionRepositoryError`.
- **Reason:** Malformed trusted-storage payloads must not escape the repository boundary as incidental Python exceptions.
- **Side effects:** More malformed SQLite rows will be rejected deterministically.
- **Tests:** Pickle a `SessionRecord(context=None)` into an existing row and require `SessionRepositoryError`.
- **Security boundary:** This hardens trusted application storage; it does not make pickle safe for attacker-controlled database files.

## A2-C03 — Enforce the same write validation for SQLite as JSON

- **File:** `app/session/repository.py`
- **Problem:** JSON `_write()` validates the session before serialization, but SQLite `create()` and `save()` do not.
- **Solution:** Call `validate_session_record_integrity(record)` before `pickle.dumps()` in SQLite create/save, preferably using a detached copy when aliasing behavior is relevant.
- **Reason:** Durable providers should reject the same invalid session state at the write boundary instead of allowing delayed restart failures.
- **Side effects:** Invalid records that previously entered SQLite will be rejected immediately.
- **Tests:** Invalid `ArchitecturePlan`, cross-run decision/message/output, invalid final result, and invalid metadata should be rejected by SQLite create/save.

## A2-C04 — Make the in-memory repository defensive

- **File:** `app/session/repository.py`
- **Problem:** `InMemorySessionRepository.create()`, `get()`, and `save()` retain or return live `SessionRecord` instances.
- **Solution:** Deep-copy values entering and leaving the repository. Keep `list()` behavior consistent with this rule. Validate the candidate before replacement.
- **Reason:** A process-local repository should not have weaker isolation than the persistence-backed providers, and callers should not mutate stored state merely by retaining a reference.
- **Side effects:** Direct callers must use `save()` to persist mutations instead of relying on aliasing.
- **Tests:** mutate an object returned by `get()` and assert the stored object is unchanged; mutate a source record after `create()`/`save()` and assert stored state is unchanged.

## A2-C05 — Complete JSON nested container validation

- **File:** `app/session/json_repository.py`
- **Problem:** Top-level, `record`, and `context` mappings are checked, but nested containers such as `worker_outputs` are still assumed to have the expected type. A malformed list can produce `AttributeError` from `.items()`.
- **Solution:** Explicitly check all collection/container types before indexing/iteration. Convert reconstruction failures to `SessionRepositoryError`.
- **Reason:** Fail-closed JSON corruption handling should be uniform for all persisted fields.
- **Side effects:** Malformed files previously leaking implementation-specific exceptions will be rejected consistently.
- **Tests:** wrong container types for messages, artifacts, decisions, execution results, worker outputs, architecture plan, and final result.

## A2-C06 — Optional JSON crash-durability improvement

- **File:** `app/session/json_repository.py`
- **Problem:** Basic atomic publication is present, but the temp filename is fixed per target and no explicit file `fsync()` occurs before replacement.
- **Solution:** Use a unique sibling temp file, write/flush/fsync it, then `os.replace()` it into place; remove the unique temp file on error.
- **Reason:** Strengthens crash durability and avoids temp-file collisions between independent repository instances without changing the backend architecture.
- **Side effects:** Additional filesystem operations.
- **Tests:** replacement failure preserves the previous published file; temp file is cleaned up; independent writers do not share a temp path.
- **Guarantee boundary:** This still does not make JSON a multi-process transactional store.

## A2-C07 — Keep `app/runtime/persistence.py` unchanged

- **File:** none
- **Reason:** Backend selection and location validation are already explicit and no A2 defect was confirmed there. Avoid unrelated changes.

## A2-C08 — Keep workflow and human-approval boundaries unchanged

- **Files:** none
- **Reason:** `RunContext.transition_to()` and the coordinator remain authoritative for workflow transitions and Gates. Persistence hardening must only reject inconsistent data; it must never add transitions, resolve gates, or replay runs.

## Implementation order

1. Harden `validate_session_record_integrity()` and SQLite identity binding.
2. Add SQLite write validation.
3. Make InMemory repository copy-on-read/copy-on-write.
4. Complete JSON nested shape validation.
5. Optionally harden JSON temp-file publication with unique temp files and `fsync()`.
6. Integrate candidate tests and execute the focused A2 suite plus the complete existing suite.

## Acceptance gate

A2 should remain blocked until the focused regressions pass against the integrated implementation and the full project test suite is executed. No production change from this delegated package should be considered integrated until the project lead accepts it.
