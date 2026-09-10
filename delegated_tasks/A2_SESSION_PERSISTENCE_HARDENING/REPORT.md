# A2 — Session Persistence Hardening Audit

## 1. Audit identity

- Repository: `AaronGabrielD/2Nombre-universal-agent-runtime`
- Audited branch: `main`
- Audited commit: `00777ce5d228de1dd4bb59bbdb07fbede2f5434a`
- Baseline commit message: `revert: remove delegated task from main`
- Audit mode: source-level inspection of the actual `main` tree through GitHub
- Production files modified by this task: **none**
- Integration status: **not integrated**; this package is review material for the project lead

### Important validation limitation

The repository could not be cloned into the local execution environment because outbound GitHub DNS/network access was unavailable. Therefore no project test suite was executed from a local checkout by this audit agent. No CI run was found for the audited `main` commit either. All claims below distinguish static evidence from executed-test evidence.

## 2. Baseline files verified as present

The requested A2 files are present on `main`:

- `app/session/manager.py`
- `app/session/repository.py`
- `app/session/json_repository.py`
- `app/session/models.py`
- `app/runtime/persistence.py`

Related contracts/models inspected:

- `app/core/contracts.py`
- `app/core/contracts_validation.py`
- `app/core/models.py`
- `app/core/states.py`
- `app/core/exceptions.py`
- `app/runtime/bootstrap.py`
- `app/runtime/service.py`
- `app/identity/authorization.py`
- `docs/M28_PERSISTENCE_MIGRATIONS.md`
- `docs/M31_CONTRACT_AUDIT.md`
- existing persistence tests `tests/test_session_sqlite.py` and `tests/test_m27_m28_persistence.py`
- `.github/workflows/tests.yml`

## 3. Executive result

**Result: APPROVED_WITH_WARNINGS**

The A2 audit is complete as a static source audit, but `main` contains real persistence-integrity defects that should be hardened before treating A2 as fully robust. The most important confirmed defects are:

1. JSON and SQLite both trust the storage key/file name and the embedded `SessionRecord.context.run_id` independently, allowing a mismatched persisted record to be returned for the requested run.
2. JSON reconstruction is not fully fail-closed for malformed top-level or nested shapes because some `AttributeError` paths escape the repository's `SessionRepositoryError` boundary.
3. JSON and SQLite reconstruction do not invoke the M31 contract validators, so type-correct `SessionRecord` objects can be resurrected with invalid child contract state.
4. `InMemorySessionRepository` returns live mutable `SessionRecord` objects, unlike the durable repositories, creating a provider-consistency and isolation gap.

The JSON write path already performs a temp-file write followed by `os.replace`, so the normal single-repository-instance update path is materially safer than a direct in-place write. The M28 documentation also explicitly limits the JSON backend to single-process / low-contention usage; this audit does not infer a multi-process guarantee.

## 4. Findings

### A2-01 — JSON filename/payload run identity mismatch

- Classification: **FAILURE**
- File: `app/session/json_repository.py`
- Location: `JsonFileSessionRepository.get()` and `_from_dict()`; `list()` also lacks filename-to-record identity validation
- Severity: **HIGH**

**Observed behavior**

`get(run_id)` selects `<root>/<run_id>.json`, but `_from_dict()` reconstructs the `RunContext` exclusively from the JSON payload. It does not receive or compare the requested/file-derived `run_id`. Therefore a valid JSON document stored as `A.json` can contain `context.run_id == "B"`, and `get("A")` will return a `SessionRecord` whose context belongs to B.

`list()` has the same identity gap because it iterates filenames but calls `_from_dict(payload)` without binding the payload to `path.stem`.

**Evidence**

- `app/session/json_repository.py` constructs the path from `run_id` in `_path()` and then calls `_from_dict(payload)` without an expected identity check. fileciteturn3file0L2
- `SessionRecord` is explicitly defined as state belonging to exactly one `run_id`. fileciteturn5file0L2
- The runtime's authorization boundary treats `RunContext.metadata["owner_user_id"]` as the ownership source for run access, so a corrupted record can affect which logical run a storage lookup appears to return. fileciteturn32file0L2

**Impact**

A damaged, copied, manually edited, or otherwise inconsistent persisted file can cause cross-run record confusion. The defect is independent of workflow-state changes and does not by itself bypass Gate A or Gate D; it corrupts the identity boundary underneath them.

**Recommendation**

Change `_from_dict()` to accept `expected_run_id`, pass the requested ID from `get()` and `path.stem` from `list()`, and reject any mismatch with `SessionRepositoryError`.

---

### A2-02 — SQLite row-key/payload run identity mismatch

- Classification: **FAILURE**
- File: `app/session/repository.py`
- Location: `SQLiteSessionRepository.get()`, `list()`, `_decode()`
- Severity: **HIGH**

**Observed behavior**

The SQLite table stores `run_id` in the primary-key column and stores a second copy inside the pickled `SessionRecord.context.run_id`. `_decode()` checks only that the decoded object is a `SessionRecord`; it never verifies that the embedded context ID matches the database row ID supplied to it.

As a result, a row keyed by `A` can decode to a record for `B`, and `get("A")` returns B's logical record. `list()` likewise returns the mismatched record without failing closed.

**Evidence**

- SQLite defines both a `run_id TEXT PRIMARY KEY` column and a pickled `payload`. `_decode()` only checks the object type and does not compare IDs. fileciteturn2file0L2
- `SessionRecord` defines all mutable state as belonging to one `run_id`. fileciteturn5file0L2

**Impact**

Storage corruption or inconsistent database state can produce a record for a different run than the lookup key. This is an integrity defect, not a claim that SQLite/pickle is safe against an attacker controlling the database file.

**Recommendation**

After unpickling and type-checking, require `record.context.run_id == stored_run_id`; otherwise raise `SessionRepositoryError`.

---

### A2-03 — JSON malformed-shape handling is not fully fail-closed

- Classification: **FAILURE**
- File: `app/session/json_repository.py`
- Location: `get()`, `list()`, `_from_dict()`
- Severity: **MEDIUM**

**Observed behavior**

The repository intends to translate malformed persisted data into `SessionRepositoryError`, but `_from_dict()` assumes dictionary-shaped structures before all shape checks exist. Examples include:

- top-level JSON `[]` causes `payload.get(...)` to raise `AttributeError`;
- `worker_outputs` stored as a list reaches `.items()` and can raise `AttributeError`;
- analogous nested non-mapping values can leak Python-level attribute exceptions rather than the repository's explicit storage error.

`get()` and `list()` catch several malformed-data exceptions, but not `AttributeError`.

**Evidence**

The current code wraps `OSError`, `JSONDecodeError`, `KeyError`, `TypeError`, and `ValueError`, while `_from_dict()` performs unchecked mapping operations such as `payload.get(...)` and `raw.get(...).items()`. fileciteturn3file0L2

**Impact**

Malformed durable state can escape the repository boundary through an implementation-specific Python exception. That weakens the intended fail-closed behavior and makes callers handle an unstable error surface.

**Recommendation**

Validate JSON container shapes before dereferencing them and catch/re-wrap the resulting validation failures as `SessionRepositoryError`. Keep `schema_version` strict.

---

### A2-04 — Reconstructed `SessionRecord` bypasses M31 contract validation

- Classification: **FAILURE**
- Files: `app/session/models.py`, `app/session/json_repository.py`, `app/session/repository.py`
- Location: `SessionRecord` construction and JSON/SQLite decode paths
- Severity: **HIGH**

**Observed behavior**

M31 explicitly states that provider-neutral core contracts validate types and structural invariants before downstream use. The persistence loaders reconstruct `ArchitecturePlan`, `ArtifactRef`, `ExecutionResult`, `HumanDecision`, `FinalResult`, `WorkerSpec`, and `RunContext` values but do not call the contract `.validate()` methods afterward.

Concrete examples accepted by the current JSON loader include:

- a `HumanDecision` whose `run_id` differs from the owning session;
- a `WorkerOutput` whose `run_id` differs from the session or whose dictionary key differs from `worker_id`;
- an `ArchitecturePlan` with duplicate worker IDs or unknown worker dependencies;
- a `FinalResult` whose `run_id` differs from the session;
- metadata entries that do not satisfy the declared `dict[str, str]` shape.

The same structural problem exists for SQLite because `_decode()` verifies only the outer `SessionRecord` type.

**Evidence**

- M31 documents explicit validation of `WorkerSpec`, `ArchitecturePlan`, `ArtifactRef`, `ExecutionResult`, `HumanDecision`, and `FinalResult`. fileciteturn37file0L2
- `ArchitecturePlan.validate()` checks worker count, worker types, uniqueness, and dependencies. fileciteturn7file0L2
- The JSON loader constructs these domain objects directly and returns a `SessionRecord` without a final `validate()` step. fileciteturn3file0L2
- The SQLite decoder likewise returns a `SessionRecord` after only an outer type check. fileciteturn2file0L2

**Impact**

The runtime can resurrect objects that are nominally the right Python classes but violate the invariants that downstream milestones rely on. This is especially dangerous after restart, because persisted invalid state becomes trusted runtime input.

**Recommendation**

Add a `SessionRecord.validate()` method in the existing session model and invoke it:

- before create/save at repository boundaries;
- after JSON reconstruction;
- after SQLite unpickling.

Validation must enforce ownership/association invariants without introducing any new workflow transitions.

---

### A2-05 — In-memory repository returns live mutable records

- Classification: **FAILURE**
- File: `app/session/repository.py`
- Location: `InMemorySessionRepository.create()`, `get()`, `save()`
- Severity: **MEDIUM**

**Observed behavior**

`get()` returns the exact object stored in `_sessions`, and `create()`/`save()` also store and return caller-owned objects. By contrast, `list()` already returns deep copies. The durable repositories naturally return reconstructed/copy-like values.

A caller with direct repository access can therefore mutate `RunContext.metadata`, lists, or other mutable members without calling `save()`, and the mutation is immediately visible to the stored record.

This also creates a subtle failure mode for invalid mutations: a manager can mutate a live in-memory record before a later validation/write step, leaving the repository modified even if the write operation rejects the candidate.

**Evidence**

`InMemorySessionRepository.get()` returns `self._sessions[run_id]` directly, and `save()` assigns the supplied object directly. fileciteturn2file0L2

**Impact**

Provider behavior differs by backend and the repository boundary can be bypassed unintentionally in process-local mode. This undermines the isolation intent of M01's defensive snapshots.

**Recommendation**

Store and return deep copies in `create()`, `get()`, and `save()`. Validate the copied candidate before replacement.

---

### A2-06 — Mutable `SessionMessage` / `WorkerOutput` / `FinalResult` contents can escape through references

- Classification: **VERIFIED**
- File: `app/session/manager.py`
- Location: `add_message()`, `set_worker_output()`, `set_final_result()`
- Severity: **MEDIUM**

**Observed behavior**

The manager correctly protects many read paths with `deepcopy()`, but some stored objects contain mutable members:

- `SessionMessage.metadata` is a mutable dictionary even though the dataclass is frozen;
- `WorkerOutput.output` is `Any` and can reference mutable application data;
- `FinalResult.deliverables` and `tests` contain dictionaries.

The manager stores the caller-supplied objects, and `add_message()` returns the same `SessionMessage` instance it appended.

**Evidence**

- `SessionMessage` is frozen but has `metadata: dict[str, Any]`; `WorkerOutput` has `output: Any`; `FinalResult` contains tuples of dictionaries. fileciteturn5file0L2
- `SessionManager.add_message()` returns the just-created object after storing it. `set_worker_output()` and `set_final_result()` store caller-supplied objects directly. fileciteturn1file0L2

**Impact**

With the current in-memory repository semantics, caller-held references can mutate session state without an explicit repository save. The durable backends are less exposed because they serialize/copy on save, which is another provider inconsistency.

**Recommendation**

The preferred A2 fix is to make repository boundaries copy-on-write/copy-on-read consistently. That closes this issue without changing the manager's public API.

---

### A2-07 — JSON write path uses atomic replacement in the documented single-process scope

- Classification: **VERIFIED**
- File: `app/session/json_repository.py`
- Location: `_write()`
- Severity: **NONE / positive control**

**Observed behavior**

The current implementation writes the JSON to a sibling `*.json.tmp` file and then calls `os.replace(temp, path)`. This avoids directly truncating the published session document during a normal write.

**Evidence**

The implementation writes the temp file, calls `os.replace()`, and removes the temp file on failure. fileciteturn3file0L2

**Impact**

This is the correct basic atomic-publication pattern for the stated backend scope.

**Recommendation**

Keep atomic replacement. Harden it by using a unique temp filename per write and `flush()+os.fsync()` before replacement, especially to avoid temp-file collisions between multiple repository instances and to improve crash durability. Do not claim this makes the backend transactional across processes.

---

### A2-08 — JSON identifier path checks block ordinary traversal characters

- Classification: **VERIFIED**
- File: `app/session/json_repository.py`
- Location: `_path()`
- Severity: **NONE / positive control**

**Observed behavior**

`_path()` rejects empty IDs and the path-separator, NUL, carriage-return, and newline characters before constructing `<run_id>.json` beneath the configured root.

**Evidence**

The current `_path()` explicitly rejects `\\`, `/`, `\x00`, `\r`, and `\n`. fileciteturn3file0L2

**Impact**

This blocks straightforward path traversal through separators in the run ID.

**Recommendation**

Keep the existing check. Optionally reject symlinks in the session-file path as a separate hardening measure for environments where the persistence directory can be manipulated.

---

### A2-09 — Repository-level locking is per instance, not a multi-process guarantee

- Classification: **VERIFIED**
- Files: `app/session/manager.py`, `app/session/repository.py`, `app/session/json_repository.py`
- Location: `_lock = RLock()` in manager/repository classes
- Severity: **LOW / documented limitation**

**Observed behavior**

The manager and each repository instance serialize their own operations with `RLock`. SQLite also relies on SQLite transaction locking for each individual connection transaction. However, the Python locks are not shared between separate repository/manager instances.

The M28 documentation explicitly says the JSON backend is intended for **single-process or low-contention durable deployments** and is not a transactional shared database replacement.

**Evidence**

- `RLock` is instance-local in `SessionManager`, `InMemorySessionRepository`, `SQLiteSessionRepository`, and `JsonFileSessionRepository`. fileciteturn1file0L2 fileciteturn2file0L2 fileciteturn3file0L2
- M28 explicitly documents single-process / low-contention scope. fileciteturn36file0L2

**Impact**

Concurrent read-modify-write through two independent repository/manager instances can still produce last-writer-wins behavior. This audit does not treat that as a violation of a claimed multi-process guarantee because none is documented.

**Recommendation**

Preserve the current scope. Do not claim multi-process safety. The JSON temp-file hardening in A2-07 reduces one class of same-path temp-file races but does not turn the backend into a shared transactional store.

---

### A2-10 — SQLite `pickle` remains trusted-storage-only

- Classification: **VERIFIED**
- File: `app/session/repository.py`
- Location: `SQLiteSessionRepository` class docstring and `_decode()`
- Severity: **DESIGN LIMITATION**

**Observed behavior**

SQLite persistence serializes `SessionRecord` with `pickle` and then uses `pickle.loads()` on read. The source explicitly documents the database as trusted application storage and warns against unpickling attacker-controlled database files.

**Evidence**

The class docstring states the trusted-storage assumption and the code uses `pickle.dumps()` / `pickle.loads()`. fileciteturn2file0L2

**Impact**

A database file controlled by an attacker must not be treated as a safe interchange format. This is an existing design constraint, not a newly discovered vulnerability in an attacker-exposed database interface.

**Recommendation**

Do not silently change the trust model in A2. Improve fail-closed type/integrity checks after unpickling, but keep the documentation that attacker-controlled SQLite databases are out of scope.

---

### A2-11 — Human-in-the-loop and workflow-state boundaries are not modified by the persistence layer

- Classification: **VERIFIED**
- Files: `app/session/manager.py`, `app/runtime/service.py`, `app/core/states.py`
- Location: `SessionManager.transition()`, coordinator Gate A / Gate D methods, state machine
- Severity: **NONE / positive control**

**Observed behavior**

`SessionManager.transition()` delegates to `RunContext.transition_to()`, which delegates to the existing state machine. Gate decisions are still validated by `RuntimeCoordinator` before state transitions. The proposed A2 hardening requires validation of persisted objects but does not add automatic transitions or alter the state machine.

**Evidence**

- `RunContext.transition_to()` uses `ensure_transition()`. fileciteturn6file0L2
- The allowed state transitions remain centralized in `app/core/states.py`. fileciteturn8file0L2
- RuntimeCoordinator requires resolved, matching approval decisions before applying Gate A/Gate D decisions. fileciteturn29file0L2

**Impact**

No evidence was found that the current A2 persistence code directly bypasses human gates. Hardening must preserve this separation.

**Recommendation**

Do not add state transitions, gate resolution, or recovery actions to repository decode/save code.

---

### A2-12 — Restart and full CRUD behavior are not execution-verified in this audit environment

- Classification: **NOT VERIFIED**
- Files: `app/session/repository.py`, `app/session/json_repository.py`, `app/runtime/persistence.py`
- Location: create/get/save/delete/list/contains and repository recreation flows
- Severity: **MEDIUM (coverage gap)**

**Observed behavior**

The implementations for create, read, update, delete, existence, list, and repository recreation are present. Existing tests cover JSON round-trip/schema/atomic-file presence and SQLite repository recreation/mutation behavior.

The tests were inspected but not executed in this audit environment. No passing result is claimed.

**Evidence**

- JSON persistence tests cover round-trip and schema/temporary-file behavior. fileciteturn24file0L2
- SQLite tests cover repository recreation and persisted mutation checks. fileciteturn23file0L2
- CI is configured to run `python -m unittest discover -s tests -p 'test_*.py' -v`, but no workflow run was associated with the audited `main` commit. fileciteturn33file0L2

**Impact**

The current happy-path persistence behavior is not independently executed by this audit agent, and the existing tests do not cover the identity mismatch and malformed-shape cases above.

**Recommendation**

Integrate the candidate A2 tests in this package and run the full suite on the integrated change before accepting A2.

## 5. Coverage matrix

| Area | Result | Notes |
|---|---|---|
| Run/session isolation | FAILURE | Identity binding is missing in JSON and SQLite reconstruction; in-memory repository also exposes live mutable records. |
| JSON create/read/update/delete/list/contains | NOT VERIFIED | Code exists; runtime execution not performed here. |
| SQLite create/read/update/delete/list/contains | NOT VERIFIED | Code exists and current tests were inspected; no test was executed here. |
| Restart persistence | NOT VERIFIED | Existing SQLite recreation test and JSON round-trip test exist, but were not run here. |
| JSON corruption fail-closed | FAILURE | Some malformed container shapes can leak `AttributeError`. |
| SQLite corruption/type rejection | VERIFIED with limitation | Non-`SessionRecord` is rejected; deeper contract validation and ID binding are missing. |
| SessionRecord invariant preservation | FAILURE | Reconstructed records are not validated against M31 contracts/ownership associations. |
| JSON atomic publication | VERIFIED | Temp file + `os.replace()` is already present. |
| JSON path traversal by separators | VERIFIED | Separators/NUL/CRLF are rejected. |
| Concurrency | VERIFIED within documented scope | Locks are instance-local; M28 documents single-process/low-contention JSON usage. |
| Workflow state machine unchanged | VERIFIED | Persistence does not define transitions. |
| Human-in-the-loop gates preserved | VERIFIED | Coordinator remains authoritative for gate decision validation. |
| Attacker-controlled SQLite file | NOT APPLICABLE as a security guarantee | Existing design explicitly treats SQLite/pickle storage as trusted application storage. |

## 6. Required hardening priority

### Priority 1 — must fix before A2 acceptance

- Bind persisted record identity to the storage key/file name.
- Validate reconstructed `SessionRecord` contents against existing runtime contracts and run ownership associations.
- Make malformed JSON shapes terminate at the repository error boundary.
- Remove live mutable-object exposure from the in-memory repository.

### Priority 2 — recommended hardening

- Use a unique JSON temp file for each write and `flush()+os.fsync()` before `os.replace()`.
- Reject symlinked session files when the persistence directory is considered mutable/untrusted.
- Add targeted corruption/tampering regression tests.

### Priority 3 — explicit non-goals

- No new persistence backend.
- No new workflow state.
- No automatic recovery/replay.
- No changes to approval gates.
- No claim of attacker-safe SQLite/pickle storage.
- No multi-process transactional guarantee for JSON.

## 7. Audit conclusion

The A2 boundary is structurally sound enough to harden in place, but it is **not ready to be treated as fully integrity-hardened**. The defects above are localized to existing session/persistence code and can be addressed without introducing a new architecture or changing the workflow state machine.
