## 1. Contracts and persistence foundation

- [x] 1.1 Define versioned PanelHandoff, PanelScope, active source context, and candidate lineage contracts without exposing local paths or image bytes.
- [x] 1.2 Add Gateway/session persistence for PanelHandoff records keyed by session, attachment hash, stable panel ID, and revision.
- [x] 1.3 Add repository/service operations to create, list, match, invalidate, supersede, and revalidate panel handoffs.
- [x] 1.4 Implement attachment ownership, existence, and content-hash validation for active source and panel lookups.
- [x] 1.5 Add backward-compatible hydration for existing sessions that have attachments and runs but no panel registry.

## 2. Source context and panel reuse

- [x] 2.1 Resolve run source context in the order explicit attachment IDs, session active source, or structured `needs_source` failure.
- [x] 2.2 Persist and restore the session active source independently from the model's textual history.
- [x] 2.3 Make dashboard decomposition query valid panel handoffs before invoking a new VLM decomposition.
- [x] 2.4 Implement stable panel matching using normalized geometry, semantic name, chart type, and bounded IoU thresholds.
- [x] 2.5 Make equivalent decomposition proposals idempotent and record explicit revisions for changed or stale panels.
- [x] 2.6 Add runtime enforcement that rejects invalid panel references instead of falling back to the full dashboard image.

## 3. Shared scoped observation pipeline

- [x] 3.1 Implement the shared PanelScopeResolver that creates a padded local crop and local-to-source coordinate transform.
- [x] 3.2 Separate PanelScope from the sensor-specific MeasurementFrame and preserve both in the common observation envelope.
- [x] 3.3 Extend OCR input and output to accept panel scope and return local and source bounding boxes with panel attribution.
- [x] 3.4 Route bar, line, pie, and scatter sensors through the same local crop resolver while retaining source-image overlays.
- [x] 3.5 Mark multi-panel full-image observations as `unscoped` and prevent automatic attribution to a specific panel.
- [x] 3.6 Add coordinate round-trip and crop-boundary tests, including titles, legends, rotated labels, and data annotations.

## 4. Agent orchestration and prompts

- [x] 4.1 Hydrate the panel inventory and active source context at the start of every Agent run, including runs created after process restart.
- [x] 4.2 Update runtime prompts and tool descriptions to require reuse-first decomposition and panel IDs for scoped OCR or measurement.
- [x] 4.3 Ensure model history cannot override structured source or panel authorization and cannot cause silent full-image fallback.
- [x] 4.4 Add structured review-gate feedback messages that tell the main Agent whether to rebind source, correct ChartSpec, retry review, or stop.
- [x] 4.5 Ensure semantic correction creates a new ChartSpec digest and candidate instead of repeating the same failed candidate.

## 5. Review recovery and publication safety

- [x] 5.1 Add source-binding preflight before tool-free VLM review and distinguish missing source from semantic review rejection.
- [x] 5.2 Extend review results with issue codes, severity, affected ChartSpec paths, suggested action, and recovery classification.
- [x] 5.3 Implement bounded review-call retries for transient provider/runtime failures.
- [x] 5.4 Return recoverable semantic failures to the Agent loop so it can assemble and render a corrected candidate.
- [x] 5.5 Persist candidate lineage, parent candidate, review attempts, source/panel refs, and unpublished status for every candidate.
- [x] 5.6 Enforce that only a passed candidate can be published and that retry exhaustion produces an explicit non-published terminal state.
- [x] 5.7 Add checkpoint transitions for source rebinding, candidate correction, review retry, and retry exhaustion.

## 6. Frontend and Gateway state presentation

- [x] 6.1 Keep “new attachment selection” separate from the session's active source attachment in run submission state.
- [x] 6.2 Make normal follow-up messages inherit the active source context without requiring a second upload.
- [x] 6.3 Display panel reuse, panel name/ID, local-scope analysis, and source-binding status in the execution view.
- [x] 6.4 Display review repair, unpublished candidate, and retry-exhausted states in Simplified Chinese with actionable next steps.
- [x] 6.5 Preserve candidate previews and review diagnostics after failure while keeping failed candidates visibly unpublished.
- [x] 6.6 Add Gateway event/replay coverage so reconnect and page reload retain source, panel, candidate, and review state.

## 7. Verification and rollout

- [x] 7.1 Add a two-run `test2` regression proving the second request reuses the first panel registry and does not decompose again.
- [x] 7.2 Add scoped OCR and bar/line/pie/scatter tests proving unrelated dashboard panels are excluded and coordinates map back to the source image.
- [x] 7.3 Add source hash change, deleted attachment, multi-attachment ambiguity, cross-session access, and stale-panel tests.
- [x] 7.4 Add review recovery tests for source rebinding, semantic correction, transient retry, duplicate-candidate prevention, and retry exhaustion.
- [x] 7.5 Add checkpoint resume tests proving completed scoped work is not replayed and review recovery resumes from a safe committed state.
- [x] 7.6 Run `conda run -n agent python -m pytest -q`, frontend build, frontend smoke tests, and a Gateway-backed real `test2` run.
- [x] 7.7 Validate the change with the repository OpenSpec CLI and document migration/rollback behavior before implementation handoff.
