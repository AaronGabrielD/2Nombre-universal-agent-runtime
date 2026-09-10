# Delegated Task — Security Authority Hardening

You are an independent audit/implementation agent. The project lead remains responsible for architecture and final integration.

## Mandatory isolation
Work ONLY under `delegated_tasks/SECURITY_AUTHORITY_HARDENING/`.
Do not modify `app/`, `tests/`, `docs/`, `.github/`, `requirements.txt`, configuration, or any existing project file outside this directory.

## Objective
Independently verify the DeepSeek supervisor's security findings against the real current `main` implementation, then produce candidate hardening material for later review.

## Audit targets
Inspect at minimum:
- `app/approval/service.py`
- `app/approval/models.py`
- `app/execution/models.py`
- `app/execution/service.py`
- `app/orchestration/service.py`
- `app/runtime/service.py`
- `app/recovery/`
- `app/tools/`
- `app/ui/chainlit_app.py`
- all relevant existing tests

## Questions
1. Human authority: determine whether `HumanApprovalEngine.resolve_gate()` can actually be invoked by a non-human runtime actor in a way that creates a valid approval. Trace real call paths. Distinguish API flexibility from an exploitable bypass.
2. Gate A: prove whether transition to `EXECUTING` requires a recorded, resolved, APPROVE decision from the correct ARCHITECTURE gate belonging to the same run. Test cross-run gate/decision reuse and fabricated decisions.
3. Gate C: verify risky-tool authorization and resume behavior, including gate ownership, worker ownership, recorded decision identity, and execution without required approval.
4. Gate D: verify `COMPLETED` cannot be reached through the integrated path without a recorded valid human approval after Supervisor PASS.
5. ExecutionAuthorization: trace all constructors/usages. Determine whether an agent/worker can fabricate `authorized=True` and whether that is a real bypass given current call paths. Do not redesign M08 merely because the DTO is structurally constructible.
6. backend_id: trace all callers of `ExecutionGateway.execute()`. Determine whether a worker/LLM/UI can influence `backend_id` to select an unauthorized backend. Distinguish internal service capability from exposed agent capability.
7. Recovery/replay: verify leases, idempotency keys, reconciliation, and explicit recovery behavior after an EXECUTING restart. Confirm no automatic replay and identify exact missing tests.

## Evidence rules
Never claim a test passed unless actually executed. Never claim external integration works without evidence. Never label a theoretical path a vulnerability without a demonstrable route from an exposed actor/input.

Classify findings as `VERIFIED`, `NOT VERIFIED`, `FAILURE`, `DESIGN LIMITATION`, or `RECOMMENDATION`.
Severity: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`.

## Deliverables
Create ONLY inside this directory:
- `REPORT.md` — executive conclusion, finding ID, classification, severity, exact file/location, evidence, exploitability/path analysis, current mitigation, recommended action.
- `PROPOSED_CHANGES.md` — exact production/test changes if any, paths, rationale, regression risks, required tests.
- `tests/` — candidate tests only; never overwrite repository tests.
- `patches/` — optional unified patches against current `main`.
- `RESULT.json` — `APPROVED`, `APPROVED_WITH_WARNINGS`, or `BLOCKED`.

## Scope prohibition
Do not create new milestones, orchestration systems, authorization architectures, providers, or unrelated refactors.

## Final acceptance condition
The package is advisory until the project lead independently validates it and explicitly integrates any accepted changes.
