## Context

See `proposal.md` for motivation and scope. The current Figura bar sensor is a JSON-only image-byte sensor under `src/figura/tools/measurements/`; its model-facing handler resolves an authorized Attachment or Panel. `RunExecutionState` reconstructs committed measurement results from tool facts, while `AgentRequestBuilder` currently includes original image blocks only after explicit `load_image` calls. RapidOCR is already a project dependency. The current registry is `figura-web-v2`, and request assembly currently rejects any historical tool call with a different registry version.

## Goals / Non-Goals

**Goals:**

- Reuse one OCR, axis geometry, and linear-calibration contract across bar, line, and scatter sensors.
- Keep source authorization in the existing attachment/Panel services and keep measurement results in durable tool facts.
- Let the model visually inspect committed measurement evidence in the next request without persisting generated image bytes.
- Preserve explicit ownership: sensor algorithms under `tools/measurements`, source-facing definitions under `tools/implementations`, run projection under `agent/execution_state.py`, and request assembly under `agent/request.py`.
- Keep uncertainty explicit and make chart-unit output conditional on a passed axis calibration gate.

**Non-Goals:**

- A general OCR tool, chart-type classifier, automatic evidence acceptance, automatic remeasurement, or a human review gate.
- OCR of arbitrary page text, pie/polar measurements, ChartSpec assembly, or frontend measurement presentation.
- Logarithmic, broken, dual, perspective, or three-dimensional axis support in this change.
- A second measurement store, a mutable active-image field, or durable overlay-image storage.

## Decisions

### 1. Keep one image-source contract and resolve bytes at the tool boundary

All three tools accept exactly `source_kind` and `source_id`. Their handlers validate the ID against the target Run's `RunExecutionState`, then resolve bytes through the existing attachment or Panel service. A small shared source-resolution helper may remove duplication among handlers, but it will not own inventory or persistence. Sensors receive bytes and return JSON-compatible evidence; they do not receive filesystem paths or mutate Run state.

This preserves Attachment and Panel authorization, supports prior-Run attachments already present in the Session inventory, and avoids requiring a preceding `load_image` call. A whole Attachment remains a whole-source measurement; callers choose a Panel when isolation is needed.

**Alternative considered:** Add image bytes, file paths, URLs, or separate optional attachment and panel fields to model arguments. These duplicate source identity, weaken the existing boundary, or expose local data, so the current two-field contract is retained.

### 2. Separate OCR, Cartesian calibration, chart sensors, and rendering

Use focused modules under `src/figura/tools/measurements/`: `ocr.py` returns bounded text candidates and their boxes; `cartesian.py` owns axis-line geometry, tick parsing/association, projection, and calibration; `bars.py`, `lines.py`, and `scatter.py` own chart-specific geometry and point semantics; `visualization.py` renders the result as an annotated image. OCR stays an internal helper and is not registered as another model-facing tool.

The adapters in `src/figura/tools/implementations/` own tool schemas, source access, and bounded error mapping. `bootstrap.py` composes those definitions. The shared axis result uses `kind`, `label_text`, `label_confidence`, `points_px`, `ticks`, and nullable `calibration`; ticks retain OCR text, nullable numeric value, text box, axis position, and confidence. Tool-specific series structures remain distinct instead of introducing a generic evidence framework.

**Alternative considered:** Port the legacy ChartAgent observation envelope wholesale. It contains additional scope, evidence-reference, and quality structures that Figura has no consumer for in this change. Only the relevant OCR, axis-calibration, and visual-feedback behavior is reused.

### 3. Gate semantic values while retaining pixel evidence

Numeric axes use a linear transform from the projection of an image point along the detected axis to a chart value. The initial acceptance gate requires at least two distinct numeric ticks, at least 40px of support span, root-mean-square residual no greater than `max(1.5, 0.08 * numeric_tick_value_span)`, and calibration confidence of at least 0.35. These initial thresholds follow the legacy Cartesian calibration approach and SHALL be locked by tests before implementation is considered complete.

For a bar, the zero baseline remains a geometric observation while the value-axis calibration maps bar endpoints to chart units. For line and scatter points, x and y values are nullable independently according to each axis's calibration. Category labels remain text/tick references, not numeric values. Failed calibration yields null semantic values, preserves pixel geometry, and produces `partial` status and warnings.

**Alternative considered:** Let the model infer values directly from pixels or OCR. That would conflate textual evidence with a validated pixel-to-value mapping and would make uncertain values look exact.

### 4. Keep chart-specific observations compact and source-coordinate based

Bar results retain current orientation, mode, baseline, series, bar geometry, signed pixel length, and ratio fields, and add axes, category association, and nullable calibrated values. Line results preserve disconnected trace polylines and add only explicit marker points or samples at recognized x-axis tick positions. Scatter results return detected point components with nullable calibrated coordinates and uncertainty flags for merged, occluded, dense, or overlapping candidates; they do not estimate an exact count of hidden points.

All geometry remains in the selected Attachment or Panel pixel coordinate system. The existing 256 KiB canonical JSON result limit remains in force. Line traces may use deterministic polyline simplification as a geometry representation; Figura SHALL NOT truncate a result prefix or silently drop measurements to fit. If a complete bounded result cannot be produced, the tool returns a bounded failure.

**Alternative considered:** Emit one sample per image pixel or infer unseen points in dense scatter regions. These approaches create oversized results or unsupported precision.

### 5. Reconstruct annotated images for the immediate next request

After a fully committed batch with successful measurement calls, the next Provider request includes the existing assistant/tool JSON interaction plus one annotated image for each successful measurement call, in persisted call order. Each annotation is generated deterministically from that call's committed result and the authorized selected source image. It identifies the tool and call ID in the adjacent text. A `no_evidence` or `unsupported` successful result may still produce an image with a status/warning annotation and no fabricated geometry.

When a batch mixes `load_image` and measurement calls, image blocks follow persisted tool-call order: explicit loads contribute original images, and measurement calls contribute their annotated images. Existing duplicate suppression for repeated `load_image` source IDs remains; separate measurements retain separate annotations. Only the immediately preceding fully committed batch contributes image blocks. Earlier JSON results remain in Session history, but older image bytes and overlays are not repeated.

The overlay is an in-memory request artifact, not a `ToolResultFact`, `RunExecutionState` field, database row, or managed source image. If the selected source can no longer be read, or the assembled image set exceeds Provider limits, request construction fails before a Provider attempt is claimed. The model decides what to do after viewing the image; warnings do not trigger automatic retries or gates.

**Alternative considered:** Persist overlay bytes or embed them in tool-result JSON. That duplicates derivable image data, increases durable payloads, and bypasses the existing Provider request image boundary.

### 6. Expand the existing execution-state projection without another owner

`RunExecutionState` keeps exactly `run_id`, `available_attachments`, `panels`, and `measurements`. Its existing `MeasurementObservation` fields remain unchanged; projection recognizes committed results from all three measurement tool names and derives them from the same Session's call, attempt, and result facts. Ordering, source-inventory validation, and exclusion of unresolved calls remain unchanged. There is no separate mutable measurement state or overlay metadata field.

**Alternative considered:** Add measurement tables or update the state from tool handlers. That creates a second source of truth and weakens the current rebuild-from-facts invariant.

### 7. Bump the registry version and treat resolved old calls as inert history

Register the expanded contracts as `figura-web-v3`. Request assembly may project a tool interaction with a different recorded registry version only when every call in its batch has a committed matching result and call ID; that interaction is conversation history, never a dispatch request. A version-mismatched pending call, unresolved attempt, or incomplete batch remains fail-closed. New calls and all handler execution still require the active v3 registry. Durable tool replay rules remain unchanged.

This narrow history rule allows a Session containing completed v2 interactions to continue without implementing v2 schemas or handlers. Deployment must not silently replay an unresolved v2 call under v3.

**Alternative considered:** Keep v2 despite the changed result contract, or retain v2 tool definitions and handlers. Keeping the old version would misidentify the contract; retaining old executable definitions would add the compatibility layer this change is intended to avoid.

## Risks / Trade-offs

- OCR may misread tick labels or associate a label with the wrong axis position → Keep raw tick text, boxes, confidence, calibration residual, warnings, and null values when calibration fails.
- Dense or noisy charts may produce large traces or many scatter points → Use a deterministic polyline representation and keep the existing result bound; reject an oversized complete result rather than silently truncating it.
- Annotated images add Provider image cost and may exceed provider image limits → Apply existing per-image, aggregate, count, and request checks before claiming the Provider attempt; fail closed if the batch does not fit.
- A source may be removed or corrupted after measurement commits but before request assembly → Resolve it again from the authorized source service and fail before Provider dispatch instead of substituting another image.
- A deployment may encounter an unresolved v2 tool call → Keep it unresolved and fail closed; do not run the call through a v3 handler.
- A line or scatter observation may be valid in pixels but unusable as a numeric value → Preserve the geometry and make semantic coordinates nullable, leaving evidence selection to the model.

## Migration Plan

1. Add the v3 definitions and update Agent history assembly in the same release so completed older call/result pairs remain readable and unresolved older calls remain blocked.
2. No database migration is required. Existing measurement facts remain unchanged; the expanded `RunExecutionState` projection reads the additional v3 tool names from committed facts.
3. Rollback does not rewrite stored facts. A rollback must not execute unresolved v3 measurement calls with an older registry; such calls remain fail-closed until the v3 implementation is restored or the Run is otherwise resolved.

## Open Questions

None. The supported chart scope, common axis contract, calibration gate, overlay lifecycle, state ownership, and registry-version policy are defined by this change.
