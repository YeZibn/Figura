## 1. Measurement evidence model

- [x] 1.1 Refactor measurement session/attempt serialization so the session exposes one current attempt with measurement/evidence refs, source scope, quality and series metadata; remove selected/discarded/decision fields and serializers.
- [x] 1.2 Remove measurement-decision lifecycle helpers and automatic event/state updates from measurement flow; make each scoped or targeted measurement call return its scope and observation result atomically.
- [x] 1.3 Preserve same-panel authorization, evidence-ref integrity, quality diagnostics and safe idempotency for explicit local measurement calls; rely on shared Agent/run execution limits, without a separate repair queue or measurement-exhausted state.

## 2. Assembly contract and model guidance

- [x] 2.1 Remove `measurement_decision`, selected/discarded refs, decision-status schemas, aliases, validation, collection handling and provenance output from `tools/chart/specification.py`.
- [x] 2.2 Validate only actual `measurement_ref`/`evidence_refs`, their source/session/scope, and ChartSpec structure; preserve generation-level source scope and coverage semantics.
- [x] 2.3 Update static and dynamic Chinese prompts plus measurement/assembly tool descriptions to teach candidate evidence use and explicit model-directed local remeasurement; remove compatibility instructions and old field names from active guidance.

## 3. Agent state and recovery

- [x] 3.1 Remove `pending_measurement_repairs`, measurement decision tracking and merge/reconstruction paths from `agent/loop.py`; derive bounded model context from current session/attempt only.
- [x] 3.2 Simplify `agent/measurement_flow.py` and `agent/recovery.py` so a completed measurement is restored without replay, decision gate or duplicate repair state.
- [x] 3.3 Remove measurement-decision fields from checkpoint, artifact index, prompt runtime projection and other persisted core models; do not add a legacy reader or data migration.

## 4. Trace and client projection

- [x] 4.1 Stop emitting measurement decision-required/selected/discarded, pending-focus and separate repair lifecycle events in new runs; retain bounded tool-call/result and required observation correlation.
- [x] 4.2 Remove obsolete measurement decision/repair fields and event branches from execution and evaluation readers plus frontend protocol/domain projections.
- [x] 4.3 Render each measurement invocation and result as one tool step, including scope, refs, quality/series metadata and overlay; show another measurement step only for an actual subsequent model tool call.
- [x] 4.4 Keep generated-chart review/publication blocking behavior and its presentation unchanged while removing measurement decision cards, labels and pending states.

## 5. Regression coverage and verification

- [x] 5.1 Replace lifecycle, assembly, tool-schema, prompt, checkpoint and recovery tests that require measurement decisions with candidate-evidence and explicit-local-call coverage.
- [x] 5.2 Add trace, evaluation-reader and frontend regressions proving new runs omit legacy measurement decision events and replay the same tool-call/result timeline.
- [x] 5.3 Verify partial/warning evidence can be selectively referenced without an acceptance decision, while invalid or cross-scope refs still fail safely and direct visual assembly remains available.
- [x] 5.4 Run focused Python tests, then `conda run -n agent python -m pytest -q`; run `cd frontend && npm run build` and `npm run smoke`; finish with `git diff --check`.
