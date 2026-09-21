## 1. Measurement evidence contract

- [x] 1.1 Define the model-facing evidence reference contract for series, bars, lines, points, sectors, legends, and other measurable candidates.
- [x] 1.2 Extend measurement attempt/session records to persist evidence refs, selected refs, discarded refs, focus mode, and parent-attempt lineage without exposing local paths or raw image bytes.
- [x] 1.3 Add compatibility normalization from the existing `series_1`/numeric candidate identities to compact model-facing refs such as `S1` and `B1`.

## 2. Shared targeted measurement input

- [x] 2.1 Extend the authorized chart measurement schemas with bounded `measurement_target.refs`, `mode`, `fields`, `reason`, and optional bbox/polygon fallback fields.
- [x] 2.2 Resolve candidate refs against the current measurement session and enrich the internal target with attachment, panel, parent attempt, source size, and target fingerprint.
- [x] 2.3 Reject cross-attachment, cross-panel, malformed, empty, out-of-bounds, duplicate, and budget-exhausted targets before dispatching a measurement tool.
- [x] 2.4 Add common target-resolution tests covering include and exclude modes, legacy bbox targets, parent-attempt validation, idempotency, and recovery after reconnect.

## 3. Measurement tool focus behavior

- [x] 3.1 Update bar measurement to apply an explicit include/exclude focus mask and remove silent fallback from a focused region to the entire panel.
- [x] 3.2 Update line, scatter, and pie measurement to use the same focus contract and return bounded `focus_empty` or `focus_insufficient` results when the target cannot produce evidence.
- [x] 3.3 Add a shared focus status payload with `requested`, `applied`, `mode`, target refs, and effective search scope to every chart measurement result.
- [x] 3.4 Update chart overlays to render compact candidate refs consistently and keep internal IDs out of user-facing semantic labels.
- [x] 3.5 Add sensor tests proving a focused call cannot silently inspect the whole panel and that the returned overlay matches the structured refs.

## 4. Main-agent decision flow

- [x] 4.1 Replace automatic measurement-repair instructions in the main loop with a compact model observation containing refs, warnings, focus suggestions, and current measurement state.
- [x] 4.2 Update the static and dynamic prompt layers to instruct the main Agent to accept, discard, stop, or call the same measurement tool with `measurement_target`.
- [x] 4.3 Record the main Agent's selected and discarded refs as an explicit evidence decision before allowing downstream assembly.
- [x] 4.4 Remove automatic measurement tool scheduling from quality-audit, review-gate, batch completion, and checkpoint recovery paths.
- [x] 4.5 Add main-loop tests proving warnings do not create a hidden retry, explicit focused calls stay in the same run, and recovery resumes at the model decision point.

## 5. Quality state and assembly gate

- [x] 5.1 Convert measurement `repair_action` handling into advisory focus suggestions while preserving issue codes, confidence, attempt lineage, repair budgets, and structured errors.
- [x] 5.2 Simplify the measurement review adapter/gate so it records evidence state and enforces hard safety constraints without deciding semantic acceptance or launching repairs.
- [x] 5.3 Extend `assemble_spec` measurement validation to require selected evidence refs from the current acceptable attempt and return `measurement_decision_required` for provisional or unresolved evidence.
- [x] 5.4 Add validation that internal refs such as `series_1` cannot become final ChartSpec series labels or rendered legend text.
- [x] 5.5 Add assembly and gate tests for accepted selections, discarded false positives, unresolved warnings, invalid refs, and exhausted focus budgets.

## 6. Persistence, observability, and UI data

- [x] 6.1 Persist waiting-for-decision, focused-measurement, selected-ref, and target-fingerprint state in checkpoints and run artifacts.
- [x] 6.2 Emit bounded trace events for evidence decision, focused measurement requested, focus applied/failed, and selected/discarded refs.
- [x] 6.3 Update evaluation and frontend readers to display the compact evidence decision and focus scope while retaining full diagnostics for inspection.
- [x] 6.4 Add reconnect and idempotency regression coverage proving completed initial or focused measurements are not repeated after resume.

## 7. End-to-end verification

- [x] 7.1 Add an end-to-end multi-series bar fixture where the main Agent rejects a legend swatch, requests an exclude focus, and assembles only the accepted bars.
- [x] 7.2 Add end-to-end coverage for line, scatter, and pie tools using the same main-chain focused measurement contract.
- [x] 7.3 Verify the existing final generated-chart VLM review and publication gate remain unchanged and still block invalid rendered candidates.
- [x] 7.4 Run focused pytest coverage, the full `conda run -n agent python -m pytest -q` suite, `git diff --check`, and relevant frontend build/smoke checks.
