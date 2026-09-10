# Delegated Task — A2 Session Persistence Hardening

## Role
You are an independent implementation/audit agent. You are NOT the project lead.

## Objective
Inspect the current `main` implementation of SessionManager and its persistence layer, then produce a self-contained candidate hardening package. Your work must remain isolated under this directory and must NOT modify `app/`, `tests/`, `docs/`, workflows, requirements, or any existing project files outside this directory.

## Scope
Audit and harden the persistence boundary for:
- `app/session/manager.py`
- `app/session/repository.py`
- `app/session/json_repository.py`
- `app/runtime/persistence.py`
- related session models/contracts used by persistence

Focus on real correctness problems only:
1. Cross-run/session isolation.
2. Restart durability for JSON and SQLite repositories.
3. Fail-closed behavior for missing, corrupt, malformed, or tampered persisted data.
4. Atomic JSON writes and safe path handling.
5. Repository consistency for create/get/save/delete/list/contains.
6. Thread/concurrent access safety within the repository's stated process-local guarantees.
7. Preservation of valid SessionRecord data across serialization/deserialization.
8. No accidental weakening of existing state-machine or Human-in-the-loop invariants.

## Important security rule
Do not introduce unsafe deserialization behavior. The current SQLite repository explicitly treats its database as trusted application storage because it uses pickle. Do not silently change that assumption or claim SQLite persistence is safe for attacker-controlled files. Identify the limitation clearly if it remains.

## Deliverables
Create ONLY inside this directory:
- `REPORT.md` — findings classified as VERIFIED / NOT VERIFIED / FAILURE / NOT APPLICABLE.
- `PROPOSED_CHANGES.md` — exact recommended code/test changes, with file paths and rationale.
- `tests/` — candidate tests only; they must be standalone copies/additions and must not overwrite repository tests.
- `patches/` — optional unified diffs against current `main`, one patch per project file that you propose changing.
- `RESULT.json` — machine-readable summary with `status` = `APPROVED`, `APPROVED_WITH_WARNINGS`, or `BLOCKED`.

## Validation requirements
You must inspect the actual repository code on the checked-out `main` branch before writing conclusions. Do not invent files, tests, APIs, CI results, or runtime behavior.

For every finding, cite the exact source path and relevant code location. Distinguish:
- confirmed defect,
- missing test coverage,
- design limitation,
- recommendation only.

## Acceptance criteria
A successful result:
- touches no project implementation files outside `delegated_tasks/A2_SESSION_PERSISTENCE_HARDENING/`;
- does not introduce new architecture or new milestones;
- includes executable candidate tests for every claimed defect/hardening change;
- keeps scope limited to A2 session/persistence integrity;
- never claims a test passed unless it was actually executed and evidence is recorded;
- never claims a production change is merged.

## Final rule
The project lead will independently review and validate your package. Nothing under this directory is authoritative until accepted and integrated by the project lead.
