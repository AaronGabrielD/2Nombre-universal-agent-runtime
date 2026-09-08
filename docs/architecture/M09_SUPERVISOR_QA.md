# M09 — Supervisor & QA

## Purpose

M09 evaluates evidence produced by workers and execution backends. It is the quality-control boundary between execution and final human approval.

## Responsibilities

- Validate that a run produced worker outputs.
- Detect unsuccessful worker states.
- Detect execution errors, timeouts, denials, and unavailable backends.
- Detect missing acceptance criteria.
- Produce a deterministic `QAResult` with score, findings, blocking issues, evidence, and recommended next action.
- Keep evaluation independent from session mutation and UI.

## Critical hierarchy rule

A `PASS` result is **not** equivalent to completion.

```text
M08 execution
      |
      v
M09 Supervisor / QA
      |
      +---- REVISE ----> revision cycle
      |
      +---- FAIL ------> failed run
      |
      +---- PASS ------> Gate D / final human approval
                              |
                              +---- APPROVE -> COMPLETED
                              +---- REJECT  -> REJECTED
                              +---- MODIFY  -> REVISION
```

The supervisor cannot bypass the human approval gate and cannot mark a run `COMPLETED` itself.

## Deterministic first

The initial M09 implementation deliberately uses deterministic checks. A future LLM evaluator may provide qualitative assessment, but it must operate as additional evidence and cannot override blocking deterministic failures or the human approval hierarchy.

## Non-responsibilities

M09 does not execute code, select tools, call Colab, present UI, or resolve human approval gates. M08 handles execution and M05 owns human gate lifecycle.
