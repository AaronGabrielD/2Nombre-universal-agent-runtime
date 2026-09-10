# Delegated Task — Security Authority Hardening

## Role
You are an independent security audit/implementation agent. You are NOT the project lead.

## Source finding
An independent supervisor reported these concerns:
- HumanApprovalEngine.resolve_gate() accepts actor strings without proving human authority.
- ExecutionAuthorization is constructible independently of a recorded human gate.
- ExecutionGateway.execute() accepts an optional backend_id override.
- Integration evidence for Gate A/C/D, execution authority, and fail-closed recovery is insufficient.

You must verify these claims against the REAL current `main` code before proposing changes.

## Objective
Produce a self-contained audit/hardening package for the runtime's authority boundaries:
1. Human approval authority.
2. Gate A / Gate C / Gate D enforcement.
3. Execution authorization provenance.
4. Backend selection authority.
5. Recovery fail-closed behavior.

## STRICT ISOLATION
You may create or modify files ONLY under:
`delegated_tasks/SECURITY_AUTHORITY_HARDENING/`

Do NOT modify `app/`, `tests/`, `docs/`, `.github/`, requirements, configuration, or any other project file.

## What to inspect
At minimum inspect:
- `app/approval/service.py`
- `app/approval/models.py`
- `app/execution/models.py`
- `app/execution/service.py`
- `app/orchestration/service.py`
- `app/runtime/service.py`
- `app/recovery/` relevant services
- Chainlit gate callback code
- existing tests covering approval, orchestration, execution, recovery

Do not assume a file exists; inspect the real tree.

## Important architectural constraints
Preserve the existing hierarchy:
HUMAN > SUPERVISOR > ARCHITECT > WORKERS

Do not:
- create a second orchestrator;
- let an LLM resolve human gates;
- bypass existing Gate A/C/D flow;
- move execution outside ExecutionGateway;
- make the UI execute code directly;
- introduce automatic replay during recovery;
- invent a new milestone.

## Required analysis
### A. Human gate authority
Determine whether a non-human caller could invoke gate resolution through a public service object and falsely identify itself as human.

Distinguish clearly between:
- API misuse possible only by trusted internal code,
- actual externally reachable bypass,
- missing defense-in-depth.

### B. Gate A
Prove or disprove that execution from the integrated orchestrator requires a recorded, resolved, approved architecture gate.

### C. Gate C
Prove or disprove that risky tools require a recorded human approval before execution.

### D. Gate D
Prove or disprove that COMPLETED requires a recorded final human approval.

### E. ExecutionAuthorization provenance
Determine whether `authorized=True` can be created without a valid gate provenance and whether that is acceptable at the M08 abstraction boundary.

Do not change provider-neutral M08 contracts merely to satisfy a test unless the evidence shows a real authority problem.

### F. Backend selection
Determine whether `backend_id` can be abused to select an unauthorized backend and whether the current callers expose that capability to workers/UI/LLMs.

### G. Recovery
Inspect replay/recovery services and prove or disprove that uncertain execution can be automatically re-run after restart.

## Deliverables
Create ONLY:
- `REPORT.md`
- `PROPOSED_CHANGES.md`
- `RESULT.json`
- `tests/` candidate tests
- `patches/` optional unified diffs

## Evidence rules
Never claim a test passed unless actually executed.
Never claim a live provider works without evidence.
Classify findings as:
- VERIFIED
- NOT VERIFIED
- FAILURE
- DESIGN LIMITATION
- RECOMMENDATION

Severity:
- CRITICAL
- HIGH
- MEDIUM
- LOW
- INFO

## Acceptance criteria
A good result should tell the project lead exactly:
1. Which supervisor findings are confirmed.
2. Which are overstated or already mitigated by the current architecture.
3. Which exact tests are missing.
4. Which production changes, if any, are necessary.
5. What can be safely integrated without expanding project scope.

Nothing in this folder is authoritative until the project lead independently validates it.
