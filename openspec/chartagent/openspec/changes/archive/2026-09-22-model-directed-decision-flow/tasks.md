## 1. Evidence-use contract and compatibility

- [x] 1.1 Add `evidence_refs` to single-chart and figure-child `assemble_spec` inputs, keeping `measurement_ref` as the server-issued source identity.
- [x] 1.2 Add a compatibility adapter that maps legacy `measurement_decision.selected_refs` to `evidence_refs` and returns a structured conflict error when old and new inputs disagree.
- [x] 1.3 Refactor measurement provenance construction to record only actually referenced refs, attempt/source identity, applicable warnings, and code-owned quality facts.
- [x] 1.4 Remove the requirement that a measurement session contain selected/discarded/abandoned decision state before assembly while retaining ref, scope, lineage, failed-attempt, and ChartSpec validation.
- [x] 1.5 Add focused tests for direct visual assembly, valid partial ref use, ignored false candidates, invalid/cross-panel refs, legacy decision compatibility, and single/figure/collection inputs.

## 2. Model-facing decision context and prompts

- [x] 2.1 Replace ordinary measurement `allowed_actions`/`blocked_actions` contracts with a bounded factual summary of scope, attempts, refs, issues, candidates, publication state, and budget.
- [x] 2.2 Update static Chinese prompt assets so evidence selection, local remeasurement, ChartSpec correction, source recovery, and stopping are model choices rather than required decision phases.
- [x] 2.3 Update dynamic runtime and process-artifact prompt assets to remove mandatory `measurement_decision` and fixed `repairPhase` language while preserving authorization, structure, and publication rules.
- [x] 2.4 Update `assemble_spec` and chart measurement tool descriptions/schema text to document `measurement_ref + evidence_refs`, optional local targets, and unused candidate behavior.
- [x] 2.5 Extend prompt tests to assert the four-layer bundle exposes factual state and safety boundaries without ordinary business-action whitelists.

## 3. Model-directed generated-chart repair

- [x] 3.1 Refactor generated-review call filtering so non-terminal failures do not restrict the main Agent to a repair-kind-specific tool sequence.
- [x] 3.2 Keep hard rejection for unauthorized/stale source references, invalid candidate/review identity, terminal or exhausted recovery, and attempts to publish or finalize a failed candidate.
- [x] 3.3 Return compact review diagnostics containing candidate/review identity, bounded issues, source scope, remaining budget, and advisory `repair_hint`/`repair_kind`.
- [x] 3.4 Ensure every repaired render creates a new candidate linked to the failed parent and triggers exactly one new tool-free VLM review before publication.
- [x] 3.5 Add Agent-loop tests showing that a failed review permits alternative authorized repair tools, rejects cross-scope evidence, respects budgets, and never publishes a failed candidate.

## 4. Trace, checkpoint, and recovery semantics

- [x] 4.1 Derive evidence-use trace events from successful assembly inputs instead of creating a required measurement decision transition.
- [x] 4.2 Preserve legacy measurement decision, focus, repair-phase, and review-subcheck events as read-only diagnostic facts without turning them into pending obligations.
- [x] 4.3 Update checkpoint serialization and continuation so completed observations remain reusable and recovery does not stop solely because a decision unit is open.
- [x] 4.4 Add recovery/idempotency tests for legacy checkpoints, mixed old/new events, completed measurement reuse, uncertain-operation blocking, and candidate review continuation.

## 5. Shared frontend timeline presentation

- [x] 5.1 Update the shared run/evaluation timeline projector to suppress measurement decision, focus transition, model-turn, operation-save, and repair-phase containers from the default user view.
- [x] 5.2 Consolidate deterministic audit, semantic VLM review, gate snapshots, and replayed events into one visible review cycle per candidate attempt.
- [x] 5.3 Render only concise Chinese review start/final states plus bounded failure reasons, while keeping raw diagnostic detail reachable through existing evaluation/read-only resources.
- [x] 5.4 Preserve normal tool calls/results, generated images, terminal errors, sequence ordering, replay idempotency, and collection child failure summaries.
- [x] 5.5 Add frontend domain/component tests for no measurement-decision card, no English review subchecks, one review summary per candidate, complete failure reasons, reload, and evaluation parity.

## 6. Validation and regression

- [x] 6.1 Run targeted Python tests for specification assembly, measurement lifecycle, prompt assembly, Agent loop, review gates, checkpoint recovery, Gateway events, and evaluation projection in the `agent` Conda environment.
- [x] 6.2 Run the full Python suite with `conda run -n agent python -m pytest -q` and resolve regressions without weakening source or publication safety.
- [x] 6.3 Run `npm run build` and `npm run smoke` in `frontend`; run `npm run smoke:launcher` if launcher/Gateway lifecycle code changes.
- [ ] 6.4 Run a representative real chart flow that includes measurement candidates and one failed generated review, confirming the model can choose its repair route and only a passed candidate is published.
- [x] 6.5 Run `git diff --check` and verify no local paths, credentials, image bytes, generated evaluation artifacts, or `.chartagent/` data enter tracked changes.
