## Context

See `proposal.md` for the motivation and observable scope. The current
Dashboard implementation performs a whole-image RapidOCR pass, discovers
candidate cards from deterministic image cues, and optionally refines those
candidates with a SAM-family backend. This makes the candidate topology
dependent on text and renderer-specific whitespace patterns. It also returns
panel evidence without making the resulting local crop a first-class input for
the later chart sensors.

The revised design keeps the authorized attachment boundary, source-image
coordinate convention, multimodal `ToolResult` contract, managed visual
observation resources, and Conda `agent` runtime rule. OCR remains available as
an independent observation tool but is not part of this decomposition path.

## Goals / Non-Goals

**Goals:**

- Use the first-pass multimodal model to propose semantic regions and names.
- Use SAM as a prompt-guided boundary refiner rather than as a semantic region
  discoverer.
- Produce stable panel identities, source geometry, named crops, and managed
  resource references in one model-facing call.
- Make each crop directly consumable by later local chart analysis.
- Preserve partial results and clear provenance when VLM proposals or SAM
  refinement are incomplete.
- Keep OCR and chart-specific value measurement independently available.

**Non-Goals:**

- Do not run OCR to discover panels, associate text, or validate segmentation.
- Do not ask the decomposition tool to extract bar, line, pie, or scatter values.
- Do not assemble a ChartSpec or infer calibrated values from a crop.
- Do not make SAM responsible for naming regions or deciding chart types.
- Do not expose model checkpoints, arbitrary local paths, dense masks, or raw
  filesystem paths to the Agent.
- Do not remove the standalone `extract_text` tool.

## Decisions

### 1. Keep one public orchestration entry point

The model-facing surface remains `decompose_chart_image` so existing prompt
and tool identity references do not need an unrelated rename. Its contract is
revised to accept a bounded list of VLM region proposals. The tool coordinates
proposal validation, SAM refinement, crop persistence, and handoff metadata;
it does not perform an internal second VLM call.

The proposal shape is intentionally small and explicit:

```json
{
  "proposal_id": "proposal_2",
  "name": "Revenue by Region",
  "role": "chart",
  "chart_type": "bar",
  "bbox_norm": [0.01, 0.30, 0.35, 0.70]
}
```

`bbox_norm` uses `[x, y, width, height]` in the original image's normalized
coordinate system. Names and semantic hints come from the VLM and remain
advisory; invalid or overlapping proposals are returned as warnings or partial
regions rather than silently repaired into a different semantic layout.

### 2. Make VLM proposal the source of panel topology

The VLM decides how many semantic regions exist and which region each proposed
box represents. The decomposition tool SHALL NOT derive panel topology from
OCR, text clusters, brightness runs, or a hidden heuristic detector. For a
single clear chart, one proposal may cover the full chart. If proposals are
missing or unusable, the tool returns a bounded whole-image/advisory result
instead of inventing multiple panels.

This addresses the observed failure where a single chart card was split into
two candidate columns before SAM had a chance to correct it.

### 3. Use SAM only to refine a proposed semantic region

For each valid proposal, SAM receives a bounded box and a positive center point
in source-image pixels. The backend returns a mask-derived polygon, bbox,
confidence, and provenance. The SAM embedding is cached for one source image,
and panel count, image size, runtime, and memory use remain bounded.

SAM is not treated as a semantic classifier. It may refine the boundary of
`Revenue by Region`, but it cannot rename the region or change its chart type
from `bar` to another type. A missing checkpoint, unavailable runtime, invalid
mask, timeout, or low-quality result produces a warning and falls back to the
validated VLM bbox.

### 4. Use the semantic bbox as the crop frame

The semantic VLM bbox, expanded by a small bounded padding, is the authoritative
rectangular crop frame because chart titles, axes, legends, and annotations may
sit close to the region edge. The SAM mask and polygon are retained as boundary
evidence and optional visualization; the crop is not blindly reduced to the
smallest mask bbox.

Every crop carries:

- a stable `region_id` independent of the display name;
- a human-readable `name` and sanitized `slug`;
- source-image bbox and optional polygon;
- crop dimensions and source-origin transform;
- the segmentation source and confidence;
- a managed observation/resource reference.

The crop filename may be derived from the stable ID and slug, for example
`region_002_revenue_by_region.png`, but the filename is metadata only; later
tools use the opaque resource reference.

### 5. Persist crops through the managed visual resource boundary

Crop bytes are returned as bounded generated visual observations and persisted
by the existing run/session-managed artifact boundary. The structured result
contains opaque references, captions, dimensions, and retention metadata where
available, never an arbitrary local path. Crop count, encoded size, total run
budget, and retention follow the same bounded resource policy as other visual
observations.

If one crop cannot be persisted, the panel geometry remains available with a
bounded warning, and other crops are not discarded.

### 6. Validate proposal, mask, and crop independently

Validation is layered:

- proposal bbox is finite, in bounds, and above the minimum region size;
- sibling proposals do not overlap beyond the configured threshold unless the
  VLM explicitly marks a nested region;
- SAM mask is non-empty, in bounds, sufficiently coherent, and compatible with
  the proposal;
- crop dimensions and source-origin transform map back to the original image;
- crop resource is decodable and within size/count budgets.

Acceptance of a crop does not imply chart values or semantic correctness. The
result keeps proposal confidence, SAM confidence, resource state, and final
panel status separate.

### 7. Make crop handoff explicit for downstream sensors

The panel record exposes both the crop resource reference and a source-image
layout context. A later sensor may analyze the crop locally while retaining the
source origin for overlay and conflict reporting. The main prompt instructs the
Agent to select the appropriate crop and pass that scoped context to the
bar/line/pie/scatter sensor instead of rescanning the whole dashboard.

The decomposition tool still does not call chart sensors itself. This keeps
panel preparation separate from mark geometry, calibration, and ChartSpec
assembly while making the handoff observable and testable.

### 8. Keep OCR outside the decomposition contract

The tool does not call global OCR, local OCR retry, OCR association, or OCR
keyword classification. The output does not contain `ocr`, `text_ids`, or
`unassigned_text_ids` fields. `extract_text` remains available for a later
targeted observation when the VLM or a chart sensor cannot reliably read a
small printed value or label.

This removes OCR as a source of panel topology errors without discarding it as
a specialized text-reading capability.

### 9. Update the main prompt around the new evidence boundary

The Dashboard policy tells the Agent to visually propose semantic regions first,
call `decompose_chart_image` with those proposals, inspect the returned overlay
or crop evidence, and then route each crop to the appropriate sensor. It no
longer asks the Agent to use OCR associations as part of decomposition. The
prompt continues to state that segmentation evidence does not prove values or
a valid ChartSpec.

## Risks / Trade-offs

- [Risk] VLM misses a panel, merges two panels, or proposes overlapping boxes.
  → Require bounded normalized proposals, preserve the proposal overlay, flag
  overlaps, and return partial results rather than inventing topology.
- [Risk] SAM focuses on an inner chart object or shrinks away edge labels.
  → Use the VLM bbox as the crop frame, retain padding, and use the mask only
  as refinement evidence and validation.
- [Risk] SAM inference adds model load time and memory pressure. → Lazy-load
  the backend, cache the source embedding, cap region count/size, and preserve
  VLM-bbox fallback behavior.
- [Risk] Crop resources consume more storage than one overlay. → Bound crop
  count, dimensions, encoded bytes, run budget, and retention; persist opaque
  managed references only.
- [Risk] Model-generated names are duplicated or unsafe as filenames. → Keep
  stable sequential IDs, sanitize slugs, truncate display metadata, and never
  use names as authorization identifiers.
- [Risk] Downstream sensors ignore the crop and rescan the dashboard. → Make
  crop references part of the panel context, update the main prompt, and add an
  end-to-end handoff assertion.
- [Risk] Removing OCR from decomposition reduces small-text evidence. → Keep
  standalone OCR available for explicit, targeted follow-up rather than making
  it a hidden segmentation dependency.

## Migration Plan

1. Revise the tool schema and model-facing description to accept VLM region
   proposals and return named crop references.
2. Replace OCR-first candidate discovery with proposal validation and SAM box
   prompting; remove OCR association and local retry from this path.
3. Add managed crop persistence and panel-to-sensor handoff while preserving
   existing single-chart sensor identities.
4. Update the main prompt and trace labels to describe VLM + SAM decomposition
   and targeted OCR as separate capabilities.
5. Add fixtures and tests for the supplied multi-panel dashboard, including
   missing proposals, overlapping proposals, SAM fallback, crop persistence,
   and local sensor consumption.
6. Do not sync the revised delta into main specs or archive the change until
   the implementation and tests reflect this new contract.

Rollback consists of restoring the previous OCR-guided implementation and
prompt policy while retaining the standalone OCR and SAM backend modules.
