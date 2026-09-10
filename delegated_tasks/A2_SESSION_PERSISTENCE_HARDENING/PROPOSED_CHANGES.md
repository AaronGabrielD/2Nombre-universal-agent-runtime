# A2 — Proposed Changes

These are **candidate changes only**. Nothing in `app/`, `tests/`, `docs/`, configuration, or workflows has been modified by this task. The leader must review and integrate manually.

## Change A2-C01 — Add a canonical `SessionRecord.validate()` boundary

- **File affected:** `app/session/models.py`
- **Problem:** JSON and SQLite reconstruct `SessionRecord` instances without invoking the existing M31 contract validators. `RunContext` and session-specific association invariants are also not checked.
- **Solution:** Add `SessionRecord.validate()` to the existing model. It should validate only existing invariants; it must not add new workflow states or transitions.
- **Reason:** Persistence is an input boundary after restart. A stored object that is structurally a `SessionRecord` but internally inconsistent must fail closed before downstream use.
- **Required checks:**
  - `context` is a `RunContext`;
  - `context.run_id` is a non-empty string and `context.state` is a `WorkflowState`;
  - `context.metadata` is a string-to-string mapping, matching the declared `RunContext` contract;
  - `messages` contain only `SessionMessage` instances whose `run_id` equals the parent context ID;
  - `artifacts` contain valid `ArtifactRef` instances;
  - `decisions` contain valid `HumanDecision` instances whose `run_id` equals the parent context ID;
  - `execution_results` contain valid `ExecutionResult` instances;
  - `worker_outputs` contain valid `WorkerOutput` instances, keys equal `worker_id`, and each `run_id` equals the parent context ID;
  - `architecture_plan`, when present, passes `ArchitecturePlan.validate()`;
  - `final_result`, when present, passes `FinalResult.validate()` and its `run_id` equals the parent context ID.
- **Possible side effects:** Previously stored malformed records will become unreadable instead of silently entering the runtime. This is intentional fail-closed behavior. No workflow semantics change.
- **Tests needed:** malformed JSON/SQLite records, cross-run child records, invalid architecture plans, invalid final results, invalid metadata, and valid full-record round-trip.

## Change A2-C02 — Enforce identity binding for JSON files

- **File affected:** `app/session/json_repository.py`
- **Problem:** The storage file name and embedded `RunContext.run_id` are independent today. `A.json` can contain a record for B, and the repository returns it to `get("A")`.
- **Solution:** Change `_from_dict()` to accept an `expected_run_id`. Pass the requested `run_id` from `get()` and `path.stem` from `list()`. Reject mismatch with `SessionRepositoryError`.
- **Reason:** `SessionRecord` must remain owned by exactly one run ID across the persistence boundary.
- **Possible side effects:** Manually renamed/copied JSON files that were already inconsistent will fail closed instead of being accepted.
- **Tests needed:** `get()` mismatch, `list()` mismatch, and mismatch after simulated file corruption.

## Change A2-C03 — Make JSON decoding fully fail-closed at the repository boundary

- **File affected:** `app/session/json_repository.py`
- **Problem:** `_from_dict()` currently assumes several mapping shapes. A top-level JSON list or a nested list used where a mapping is expected can leak `AttributeError` instead of `SessionRepositoryError`.
- **Solution:** Validate container shapes before `.get()`, indexing, or `.items()`. Keep the schema-version check strict. Convert malformed reconstruction failures into `SessionRepositoryError` from `get()`/`list()`.
- **Reason:** Callers should receive one explicit persistence error contract rather than implementation-specific Python exceptions.
- **Possible side effects:** More malformed files will be rejected earlier. Valid JSON output remains unchanged.
- **Tests needed:** top-level list/scalar, non-mapping `record`, non-mapping `context`, non-list collection fields, non-mapping `worker_outputs`, invalid enum values, invalid timestamps, and missing required fields.

## Change A2-C04 — Harden JSON atomic publication without changing the backend architecture

- **File affected:** `app/session/json_repository.py`
- **Problem:** The current implementation already uses a temp file plus `os.replace()`, but every repository instance uses the same `<target>.tmp` name and the content is not flushed/fsynced before publication.
- **Solution:** Create a unique sibling temp file with `tempfile.mkstemp()`/`NamedTemporaryFile`, write the complete JSON, `flush()`, `os.fsync()`, close it, then `os.replace()` it into place. Always remove the unique temp file on failure.
- **Reason:** Avoid collisions between independent repository instances and improve durability against crashes that occur immediately after write publication.
- **Possible side effects:** More filesystem syscalls. No change to the public repository contract.
- **Tests needed:** replacement failure preserves the old target, no temp file remains, and concurrent independent writers do not share a temp filename.
- **Boundary:** This does **not** create a multi-process transactional repository and must not be documented as one.

## Change A2-C05 — Reject symlinked JSON session files when storage integrity is part of the local boundary

- **File affected:** `app/session/json_repository.py`
- **Problem:** `get()`/`list()` use normal file following semantics. A manipulated `run_id.json` symlink can make the repository read a file outside the configured root.
- **Solution:** Before reading a session file, reject `Path.is_symlink()` with `SessionRepositoryError`. The same guard should apply to `save()`/`delete()` if the path already exists as a symlink.
- **Reason:** The configured persistence root should not become an unintended file-following primitive.
- **Possible side effects:** Existing installations that deliberately use symlinked session files will stop loading them. This is a hardening option for integrity-sensitive deployments.
- **Tests needed:** symlinked session file is rejected on platforms where symlinks are available.

## Change A2-C06 — Bind SQLite row identity to decoded record identity

- **File affected:** `app/session/repository.py`
- **Problem:** SQLite stores `run_id` both as the row primary key and inside the pickled payload, but `_decode()` checks only the outer type.
- **Solution:** After unpickling and `SessionRecord` type-checking, validate the record and require `record.context.run_id == stored_run_id`. Raise `SessionRepositoryError` on mismatch or invalid contract state.
- **Reason:** Prevent a corrupted/inconsistent row from being returned as a different logical run.
- **Possible side effects:** Existing malformed rows become unreadable, as required for fail-closed behavior. No schema change is necessary.
- **Tests needed:** row-key/payload mismatch, invalid child contracts, wrong worker-output key, wrong decision/final-result run IDs.

## Change A2-C07 — Preserve the trusted-storage boundary for SQLite/pickle

- **File affected:** `app/session/repository.py`
- **Problem:** `pickle.loads()` can execute Python deserialization behavior and must not be treated as safe for attacker-controlled DB files.
- **Solution:** Keep pickle for the existing trusted application-storage design. Catch ordinary `Exception` around `pickle.loads()` so malformed stored payloads remain inside `SessionRepositoryError`, while deliberately not claiming attacker-controlled safety.
- **Reason:** This hardens the current design without silently changing the storage model or introducing a new backend.
- **Possible side effects:** Deserialization exceptions from malformed trusted rows become a consistent repository error.
- **Tests needed:** truncated pickle, non-`SessionRecord` pickle, invalid `SessionRecord` pickle, and an exception-raising `__setstate__` fixture if practical.
- **Security boundary:** A hostile user who can replace the DB file is still outside the trusted-storage model and must not be promised safety.

## Change A2-C08 — Make the in-memory repository copy-on-write/copy-on-read

- **File affected:** `app/session/repository.py`
- **Problem:** `InMemorySessionRepository.get()` returns the exact stored `SessionRecord`, and `create()`/`save()` retain caller-owned objects. Durable providers do not have identical aliasing semantics.
- **Solution:** Deep-copy records entering and leaving the repository. Validate a detached candidate before replacing the stored value.
- **Reason:** Preserve the M01 defensive-snapshot intent and make repository provider behavior materially more consistent.
- **Possible side effects:** Callers can no longer mutate stored state through a previously returned object; explicit `save()` remains the mutation boundary.
- **Tests needed:** mutate result of `get()` and assert stored state is unchanged; mutate a caller-owned record after `create()`/`save()` and assert repository state is unchanged.

## Change A2-C09 — Validate before durable/in-memory replacement

- **Files affected:** `app/session/repository.py`, `app/session/json_repository.py`
- **Problem:** Invalid application-created `SessionRecord` values can currently reach persistence without a unified session-level validation call.
- **Solution:** Call `record.validate()` before create/save. For decoded JSON/SQLite records, call `record.validate()` after reconstruction and before returning.
- **Reason:** Fail-closed behavior should apply both to stored-data recovery and to the write boundary.
- **Possible side effects:** Code that previously persisted invalid objects will receive a validation error. This is an intentional enforcement of already-documented contract invariants.
- **Tests needed:** invalid create/save rejection for all repositories.

## Change A2-C10 — Do not change `app/runtime/persistence.py`

- **File affected:** none
- **Problem:** No A2 correctness defect was confirmed in backend selection/config validation itself.
- **Solution:** Leave current backend selection intact. It already recognizes `memory`, `json`, and `sqlite`, validates required durable locations, and constructs the corresponding existing repository classes.
- **Reason:** Avoid scope creep and preserve M44 composition behavior.
- **Possible side effects:** None.
- **Tests needed:** Keep/extend existing backend-selection tests only if the project lead has a gap; not required by this audit.

## Change A2-C11 — Keep workflow state and human gates untouched

- **Files affected:** none
- **Problem:** None found in A2 persistence that requires changing the state machine or approval flow.
- **Solution:** Do not add transitions, gate resolution, recovery actions, or automatic replay to session repositories. Persistence hardening stops at validating stored state and preserving identity.
- **Reason:** `RunContext.transition_to()` and `RuntimeCoordinator` remain the authoritative state/gate boundaries.
- **Possible side effects:** None.
- **Tests needed:** Regression test that invalid persisted state is rejected, while valid `WAITING_*` states remain reconstructable exactly as stored.

## 3. Suggested integration order

1. `app/session/models.py`: add `SessionRecord.validate()`.
2. `app/session/repository.py`: enforce validation, identity binding, and in-memory copying.
3. `app/session/json_repository.py`: enforce identity binding, shape validation, optional symlink rejection, and safer atomic writes.
4. Integrate candidate tests from this package.
5. Run the project's full `unittest` suite and the focused A2 candidate tests on the integrated branch.
6. Manually verify restart recovery against JSON and SQLite using the runtime's existing recovery path. No automatic replay behavior should be introduced.

## 4. Explicit non-goals

- Do not add a new persistence provider.
- Do not add a new session data model outside the existing session model.
- Do not add workflow states.
- Do not alter Gate A, Gate C, or Gate D semantics.
- Do not change the recovery state machine.
- Do not remove SQLite/pickle solely because it is unsafe for hostile storage; the current documented boundary is trusted application storage.
- Do not claim JSON is transactionally safe across multiple processes/instances.
