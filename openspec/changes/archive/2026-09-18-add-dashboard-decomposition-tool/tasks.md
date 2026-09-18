## 1. Semantic proposal and result contract

- [x] 1.1 Replace the OCR-oriented decomposition envelope with a VLM proposal, panel identity, segmentation provenance, crop reference, confidence, and warning contract.
- [x] 1.2 Define bounded normalized region proposals with `name`, `role`, optional `chart_type`, and `[x, y, width, height]` bbox validation.
- [x] 1.3 Define stable region/panel IDs, sanitized slugs, display names, source-coordinate transforms, and crop metadata.
- [x] 1.4 Remove `ocr`, `text_ids`, `unassigned_text_ids`, and OCR-association requirements from the decomposition result.

## 2. VLM-provided region handling

- [x] 2.1 Update the authorized model-facing tool contract so complex-image calls can carry VLM-proposed semantic regions.
- [x] 2.2 Validate proposal bounds, minimum sizes, finite coordinates, maximum panel count, and sibling overlap before invoking SAM.
- [x] 2.3 Preserve proposal order and semantic identity across structured data, overlays, crops, and downstream handoff.
- [x] 2.4 Return a bounded whole-image/advisory partial result when proposals are absent or unusable without inventing OCR- or brightness-derived topology.

## 3. SAM-guided boundary refinement

- [x] 3.1 Reuse the backend-neutral segmentation interface with VLM proposal boxes and positive center points as the SAM prompts.
- [x] 3.2 Keep SAM loading lazy, cache the source-image embedding, and enforce bounded panel count, region size, runtime, and memory behavior.
- [x] 3.3 Validate SAM masks for non-empty geometry, source bounds, coherence, proposal compatibility, and neighboring overlap.
- [x] 3.4 Preserve the validated VLM bbox as a partial fallback when SAM is unavailable, invalid, timed out, or below the acceptance threshold.
- [x] 3.5 Keep SAM provenance and confidence separate from VLM proposal confidence and final panel status.

## 4. Named crop generation and persistence

- [x] 4.1 Generate rectangular crops from the padded semantic proposal bbox while retaining SAM polygon/mask evidence separately.
- [x] 4.2 Persist bounded crop images through the managed visual observation/resource boundary rather than exposing local paths.
- [x] 4.3 Return opaque crop references, dimensions, source origins, stable IDs, display names, sanitized slugs, and safe captions.
- [x] 4.4 Enforce crop count, image dimensions, encoded byte, run budget, retention, and per-resource failure limits.
- [x] 4.5 Preserve valid panel geometry and other crops when one crop cannot be encoded or persisted.

## 5. Downstream panel handoff and prompt integration

- [x] 5.1 Expose panel crop references and source-image layout context in the format consumed by local bar, line, pie, and scatter analysis.
- [x] 5.2 Update the main chart-understanding prompt to require visual semantic proposals before multi-panel decomposition and to route named crops to specialized sensors.
- [x] 5.3 Remove instructions that treat OCR associations as decomposition evidence, while keeping standalone OCR available for targeted later observations.
- [x] 5.4 Ensure downstream sensors do not silently rescan the full dashboard when a valid panel crop is available.
- [x] 5.5 Keep `assemble_spec` and chart-specific sensors responsible for calibration, values, semantic association, and final validation.

## 6. Visual evidence and diagnostics

- [x] 6.1 Update the decomposition overlay to show stable panel IDs, names, proposed/refined boundaries, crop status, and warnings without OCR labels.
- [x] 6.2 Add bounded trace metadata for proposal validation, SAM source/confidence, crop persistence, and panel handoff.
- [x] 6.3 Keep partial, fallback, rejected, and accepted states distinguishable in structured output and visual evidence.

## 7. Tests and evaluation fixtures

- [x] 7.1 Add a multi-panel fixture with a text block, two bar charts, and a pie chart matching the intended VLM + SAM flow.
- [x] 7.2 Add contract tests for valid, missing, malformed, overlapping, and duplicate-name VLM proposals.
- [x] 7.3 Add segmentation tests for accepted SAM masks, invalid masks, unavailable SAM, fallback bboxes, and neighboring overlap.
- [x] 7.4 Add crop tests for source-coordinate mapping, padding, stable naming, resource references, byte limits, and per-crop failure isolation.
- [x] 7.5 Add an end-to-end test proving that each returned crop can be handed to the appropriate existing chart sensor without fabricating values.
- [x] 7.6 Add a regression test proving that the old OCR/brightness candidate logic is not required and cannot split one semantic chart card into unrelated panels.

## 8. Runtime, documentation, and verification

- [x] 8.1 Document VLM proposal format, SAM runtime configuration, crop resource limits, fallback behavior, and the canonical `agent` Conda environment.
- [x] 8.2 Update user-facing tool descriptions and trace labels in Simplified Chinese while preserving the stable English tool name.
- [x] 8.3 Run focused decomposition tests, the full Python suite, `git diff --check`, and applicable frontend/Gateway smoke checks after implementation.
