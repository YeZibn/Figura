## 1. Baseline behavior and responsibility inventory

- [x] 1.1 Inventory timeline event kinds, producers, consumers, duplicate fields, and Gate mirror events across source, Gateway, frontend, Evaluation, tests, and scripts.
- [x] 1.2 Map `Agent.run` responsibilities and transient state owners; record existing module boundaries and evidence-backed cleanup candidates.
- [x] 1.3 Add or identify regression coverage for serial tool-call order, interruption boundaries, checkpoint/resume, idempotency, pending-review recovery, and publication blocking before extraction.

## 2. Canonical timeline event contract

- [x] 2.1 Define the version-2 event-kind schema and the canonical state/status field for each participating event.
- [x] 2.2 Update the producer validator to enforce event-kind schemas, reject same-meaning aliases, and keep protocol failures bounded without changing domain outcomes.
- [x] 2.3 Migrate Agent and other event producers to remove duplicate fields and retire `review_gate_required`, `review_gate_updated`, and nested Gate snapshots.
- [x] 2.4 Keep Run-summary `executionGate` as a derived query projection only; verify it is never used to restore or mutate review state.
- [x] 2.5 Update persistence, replay, stream tests, and event allow-lists without changing routes, Run identity, sequence, or remaining supported event names.

## 3. Shared desktop timeline and Evaluation

- [x] 3.1 Update frontend protocol/domain parsing to use only each event kind's canonical fields and remove retired event branches and same-meaning fallbacks.
- [x] 3.2 Render unsupported or malformed history explicitly while preserving summaries, history-gap behavior, bounded details, and artifact/resource links.
- [x] 3.3 Verify ordinary Run and Evaluation case views use the same user-timeline projection and show one review cycle without Gate/subcheck duplicate cards.
- [x] 3.4 Update Evaluation diagnosis to consume canonical events without rebuilding domain state; preserve and test redaction, truncation, resource authorization, and directory containment.

## 4. Agent loop responsibility refactor

- [x] 4.1 Introduce a per-run execution context for transient run state and keep checkpoint serialization at the existing recovery boundary.
- [x] 4.2 Keep the public `Agent` construction, run, reset, close, and message-inspection surface stable while delegating run coordination to a focused orchestrator.
- [x] 4.3 Extract the high-level lifecycle of one tool call, reusing `turn.py`, `recovery.py`, `measurement_flow.py`, `panel_routing.py`, and `artifacts.py` rather than duplicating their responsibilities.
- [x] 4.4 Extract generated-chart review and pending-review resume coordination while keeping `ChartReviewManager` as the sole owner of review state.
- [x] 4.5 Route all timeline emissions through the canonical producer boundary; do not add a second timeline projector or Gate state owner.
- [x] 4.6 Preserve and regression-test tool ordering, interruption checks, checkpoint ordering, uncertain-operation handling, review blocking, and publication behavior after each extraction.

## 5. Evidence-driven cleanup within scope

- [x] 5.1 Search production code, tests, scripts, frontend, protocol consumers, and persistence readers for retired event kinds, duplicate fields, and obsolete aliases.
- [x] 5.2 Migrate in-repository callers and tests away from obsolete private wrappers/exports before removing those wrappers.
- [x] 5.3 Remove only code proven unused or redundant by the reference audit; retain intentional public façades, checkpoint infrastructure, and Evaluation safety boundaries.
- [x] 5.4 Confirm no unrelated repository-wide cleanup, data deletion, or review/measurement state redesign entered the change.

## 6. Verification

- [x] 6.1 Run focused Python event, Gateway, Agent, recovery, review, and Evaluation tests, then the relevant full Python suite in the `agent` Conda environment.
- [x] 6.2 Run frontend build and smoke tests for ordinary-run and Evaluation history rendering.
- [x] 6.3 Verify replay/reconnect, unsupported historical versions, review blocking/publishing, idempotency, and Evaluation safety boundaries end to end.
- [x] 6.4 Confirm `git diff --check` passes and review the final change for deleted call sites, duplicated state, and compatibility fallbacks.
