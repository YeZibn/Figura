## Context

See `proposal.md` for motivation. The current Figura measurement boundary is under `src/figura/tools/`: tool definitions resolve authorized source IDs, sensors return bounded JSON, and `RunExecutionState` reconstructs committed chart measurements from existing tool facts. OCR is already an internal helper used by the Cartesian sensors. The Agent reconstructs transient measurement overlays for the next Provider request; image bytes are not part of tool results. The current web registry is `figura-web-v3`.

## Goals / Non-Goals

**Goals:**

- Give OCR and all four chart measurements the same bounded source-relative region contract.
- Expose the existing OCR evidence as an authorized Figura tool while retaining its fallible-evidence semantics.
- Add a pie-specific polar observation contract that shares source, scope, OCR, and transient-image boundaries without routing pie data through Cartesian axes.
- Keep Run facts as the durable source of truth and keep the Provider request boundary responsible for transient images and request limits.

**Non-Goals:**

- Add durable scope records, OCR state, overlay storage, database tables, Gateway endpoints, or frontend scope controls.
- Port the legacy chart observation envelope, measurement targets, layout hints, evidence references, focus metadata, or generated-image payloads.
- Infer source data values from OCR labels, pie colors, or apparent sector text; add donut, exploded, perspective, elliptical, or 3D pie support.
- Change the existing bar, line, or scatter output schemas beyond accepting and applying the scope input.

## Decisions

### 1. Use one normalized polygon scope for all five observation tools

`observation_scope` is optional on `extract_text`, `measure_bars`, `measure_lines`, `measure_scatter`, and `measure_pie`. Its only fields are optional `include` and `exclude` arrays. Each supplied array has 1–4 polygons; each polygon has 3–32 `[x, y]` integer points; each coordinate is in `0..1000`. A scope must supply at least one of the two arrays. An omitted include means the full source. Multiple include polygons form a union, then the exclude union is subtracted. Exclusions win where polygons overlap.

Map each normalized vertex to the selected image boundary as `x_px = x * width / 1000` and `y_px = y * height / 1000`. Build the effective raster mask by testing source-pixel centers against the polygon union and exclusions. Reject malformed scopes and scopes that leave no observable pixels before OCR or measurement begins. An omitted scope means a full-image mask. Never reinterpret an invalid scope as an unscoped request.

Pass the original source dimensions and effective mask to the OCR/sensor path; do not crop and resize the image in a way that changes result coordinates. Pixels outside the mask are unavailable evidence for detection, OCR, and association. Any retained geometry and OCR box remains in the complete Attachment or Panel coordinate system. The polygon limits bound parsing and mask work while allowing the model to select irregular chart regions and exclude unrelated areas.

**Alternative considered:** Use a rectangular `bbox_px`, as in older Figura measurement targeting. That cannot represent irregular chart panels or exclude an unrelated area inside a bounding box. Resizing a crop would also require coordinate restoration in every sensor. The normalized polygons provide one shared input while preserving the current pixel-output contracts.

### 2. Keep authorization and image resolution at the existing tool boundary

Each tool accepts only its source identity plus the optional scope. Its adapter checks `RunExecutionState` membership and uses the existing Attachment or Panel service to verify ownership and read bytes. The sensor receives image data and a validated mask, never a model-supplied path, URL, or byte payload. Measurement tools continue to work without an earlier `load_image` call. Scope arguments are already preserved with the committed tool-call fact; no scope-specific store or state field is needed.

**Alternative considered:** Store the active scope on `RunExecutionState` or add a scope resource. Scope belongs to one tool call and may differ between calls, so putting it in run-wide state would create a second, ambiguous owner.

### 3. Expose `extract_text` as bounded evidence, not as measurement state

Register `extract_text` over the current OCR recognizer. A successful result contains source identity and dimensions, coordinate system, `available`, `truncated`, and up to 512 snippets with result-local IDs, text up to 128 characters, pixel boxes, and confidence in `[0, 1]`. `available` means the OCR pass completed; zero detections is an available empty result. A readable source with OCR unavailable produces `available: false` and no snippets. Source authorization and image-read errors still use the ordinary bounded tool failure.

Set `truncated` when either the snippet count or a recognized string exceeds its output bound. Keep OCR in ordinary committed tool-call/result history; do not put it in `RunExecutionState.measurements`. This lets the Agent inspect text without adding another state projection or declaring OCR to be chart measurement.

**Alternative considered:** Return the legacy nested observation envelope with evidence, source, and quality structures. Figura has no consumers for that envelope; its concise snippet fields already match the internal OCR evidence used by its sensors.

### 4. Keep pie geometry polar and use the current measurement naming family

Register `measure_pie`, matching `measure_bars`, `measure_lines`, and `measure_scatter`. Reuse the authorized source resolution, validated scope mask, OCR helper, bounded result path, and visualization flow, but give pie its own sensor and result contract. The sector geometry is represented by a detected circle (`plot_region.center_px`, `plot_region.radius_px`) plus each sector's start angle and sweep. Angles begin at 12 o'clock and increase clockwise. This representation is source-relative and handles sectors crossing zero without creating a point cloud or forcing Cartesian axes.

Ratios are angular shares (`sweep_angle_deg / 360`) and are never inferred from OCR text or color. Use the legacy sensor's evidence gates as the initial bounded rule: circular angular coverage at least `0.80`, mean radial support at least `0.56` for a sector ratio, total observed sweep within `12` degrees of `360`, and ratio total within `0.035` of `1.0` before status is `measured`. A sector without adequate boundary support has a null ratio. If any ratio or total-coverage gate fails, preserve supported angles, set status to `partial`, and explain the gap in warnings. A readable image without detected pie geometry is `no_evidence`; detected non-circular, donut, exploded, perspective, or 3D geometry is `unsupported` and does not claim ratios.

Keep the output specific and compact: source identity, dimensions, coordinate system, status, nullable plot region, ordered sectors, confidence (`overall`, `geometry`, `segmentation`, `association`), and warnings. Each sector carries a result-local integer ID, start angle, sweep, nullable ratio, nullable hex color, nullable OCR-associated label and confidence, plus confidence. Do not add Cartesian axes, dataset values, legend tables, polar transform metadata, or legacy evidence-reference fields.

**Alternative considered:** Reuse the legacy `extract_pie_slices` result envelope or route pie through the Cartesian sensor. The first carries layout/evidence/focus payloads with no Figura consumer; the second would assign meaningless x/y axes to a circular measurement. `measure_pie` and the polar result keep the capability consistent with Figura's current tool family without carrying that baggage forward.

### 5. Extend only the existing committed-measurement projection

Add `measure_pie` to the tool names recognized by the `RunExecutionState.measurements` projection. It remains reconstructed from the existing call, attempt, and result facts, ordered with the existing measurements, and validated against the authorized source inventory. OCR remains in the ordinary tool interaction history. No fact schema, table, projection field, mutable runtime state, or Gateway payload is added.

**Alternative considered:** Create a separate pie or OCR state collection. Both results already have durable tool facts, and OCR is not a measurement; another collection would duplicate existing ownership.

### 6. Reconstruct OCR and pie visual feedback for the next request

After a fully committed batch containing a successful `extract_text` or `measure_pie` call, reconstruct one temporary annotation per successful call using the authorized original source and committed JSON result. OCR annotations draw the returned text boxes and IDs; pie annotations draw the detected circle and supported sector boundaries. Keep their JSON tool observations in the paired tool messages. Generate images only while building the immediately following Provider request, apply existing image-count and byte limits before claiming the Provider attempt, and do not persist annotated bytes.

The Agent request path handles the new visual results alongside current explicit `load_image` originals and Cartesian measurement overlays. If a required source can no longer be resolved or an annotation cannot be rebuilt, fail request assembly before a Provider attempt rather than substituting another image or omitting required feedback. Warnings remain candidate evidence and do not trigger retries or gates.

**Alternative considered:** Put image bytes in `ToolResultFact` or add an image-serving API. Both duplicate source-derived data and widen durable/API boundaries; reconstructing from committed results and authorized source bytes reuses the existing request lifecycle.

### 7. Advance the registry contract without retaining executable aliases

Register the new tool contracts in `figura-web-v4`. A changed tool schema is a new registry contract. Completed old-registry interactions remain inert history under the existing Agent rule; unresolved or incomplete calls stay fail-closed. Do not retain alias tool names or old handlers. There is no storage migration because the existing fact format stores call arguments and JSON tool results.

**Alternative considered:** Keep v3 or register both old and new definitions. Keeping v3 would misidentify the expanded registry; aliases would create the compatibility layer the change is intended to avoid.

## Risks / Trade-offs

- A polygon mask can cut through text or chart geometry → Keep source-pixel coordinates, treat masked pixels as unavailable, preserve only supported evidence, and return partial status or warnings when the scope leaves evidence incomplete.
- A model-selected scope can omit relevant chart content → The default remains the full source, and the tool returns candidate evidence; the Agent can choose another scope in a later call without an automatic retry.
- OCR bounds may truncate text useful for measurement → Set `truncated` explicitly and preserve the complete durable tool result within the existing result-byte limit.
- Pie colors may be hard to distinguish or a circle may be obscured → Gate ratios on coverage and boundary support, retain null ratios and warnings, and report unsupported shapes without treating them as data.
- Transient annotation reconstruction requires the source to remain readable after a tool result commits → Resolve the authorized source again before Provider-attempt claim and fail closed if it is unavailable.
- Five tools now accept a shared nested scope schema → Define and validate the same schema once in the tool layer, then bind each adapter to its own sensor behavior to prevent contract drift.

## Migration Plan

1. Implement the shared scope contract, tool registrations, pie projection, and request annotations as one registry-v4 change.
2. No database or Gateway migration is required; scope stays in existing call arguments and tool outputs stay in existing result facts.
3. On rollback, do not reinterpret v4 tool calls under an older registry. Completed prior-version interactions remain history; unresolved calls remain fail-closed until the v4 implementation is restored or the Run is explicitly resolved through the existing recovery boundary.

## Open Questions

None. Scope shape and bounds, pie output fields and ratio gates, transient feedback lifecycle, state ownership, and registry version are defined by this proposal.
