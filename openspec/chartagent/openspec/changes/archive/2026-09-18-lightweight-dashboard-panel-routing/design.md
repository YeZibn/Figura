## Context

See `proposal.md` for the motivation. The current dashboard tool accepts VLM
normalized regions and can emit preview crops, but its default segmentation
policy may load an optional SAM backend. The Agent caches a layout context for
`panel_id`, while chart sensors still open the source attachment and use the
context mainly as a measurement hint. The implementation must preserve the
authorized attachment boundary, source-image coordinates, existing generated
image observation transport, and the ability to run in the `agent` Conda
environment without a SAM installation or checkpoint.

## Goals / Non-Goals

**Goals:**

- Make deterministic VLM-bbox validation and padded rectangular scopes the
  default dashboard decomposition behavior.
- Define one panel handoff that connects decomposition, Agent routing, and all
  four chart sensors.
- Let sensors constrain their pixel search to a resolved panel scope while
  independently detecting the chart-specific plot frame and calibration.
- Preserve source origins, transforms, panel identity, crop previews, warnings,
  and bounded fallback behavior.
- Keep SAM available only as an explicit optional backend without making it a
  runtime or configuration dependency.

**Non-Goals:**

- Removing the SAM adapter completely or adding a new segmentation model.
- Using OCR to discover dashboard topology or associate panels automatically.
- Solving precise inner plot-frame detection for every chart in the decomposition
  call itself.
- Introducing a new persisted attachment protocol for derived crops in this
  change.
- Fabricating chart values, axes, or ChartSpec data during decomposition.

## Decisions

### 1. Use a deterministic rectangular scope as the primary segmentation result

`decompose_chart_image` will validate VLM proposals, apply bounded padding, and
create a rectangular `AnalysisScope`. This matches dashboard card geometry,
avoids optional model startup, and makes behavior reproducible. The existing SAM
adapter remains behind an explicit mode for future experiments, but `auto` will
not activate it from a configured checkpoint.

Alternatives considered:

- Keep SAM as the default: rejected because its mask currently does not define
  the crop consumed by sensors and adds latency and failure modes.
- Delete SAM entirely: deferred so future irregular-panel experiments retain a
  reversible extension point.

### 2. Treat `panel_id` as a runtime routing handle, not just metadata

The decomposition result and Agent checkpoint state will retain a bounded
panel index keyed by source attachment and panel ID. The index contains the
source scope, source origin, local-to-source transform, chart hint, and
uncertainty. When a geometry tool call includes `panel_id`, the Agent resolves
the matching entry before dispatch. An unknown or cross-attachment panel will
produce a bounded routing failure or an explicitly labeled fallback, never an
unrelated full-dashboard measurement.

The first implementation will use the authorized source attachment plus an
internal ROI rather than registering a new filesystem-backed derived
attachment. Generated crop bytes remain available to the model and frontend
through the existing visual-observation path.

### 3. Separate panel scope from measurement frame

The resolved panel scope limits where a sensor searches. It does not assert
that the full card is the plot. Sensors will preserve or add a chart-specific
measurement frame inside that scope, while title, legend, axis labels, and data
labels remain separate annotation evidence. This prevents a dashboard card's
legend swatches or title text from being treated as bars, lines, or sectors.

### 4. Preserve source-coordinate attribution

Sensor internals may operate in local scope coordinates for simpler image
processing, but every serialized geometry, overlay, and warning reference will
retain the source attachment and map local coordinates back using the declared
origin and scale. This avoids a second coordinate convention for crops and
keeps evidence fusion compatible with existing chart tools.

### 5. Keep decomposition OCR-free

No global OCR, text clustering, or OCR-based panel assignment will be added to
the decomposition path. Targeted OCR remains an Agent decision after a panel is
resolved, when a chart sensor needs labels, ticks, legends, or data values.

## Risks / Trade-offs

- **[VLM bbox is too loose]** → Validate bounds and overlap, use bounded
  padding, report scope confidence, and let each sensor independently detect
  its inner measurement frame.
- **[VLM misses a panel]** → Preserve the current bounded partial/whole-image
  fallback and make the warning explicit; do not infer topology from OCR.
- **[Local sensor coordinates drift]** → Require source origin and transform in
  the handoff and add source-coordinate regression assertions for every chart
  type.
- **[Chart content lies near a panel edge]** → Keep crop padding and retain
  annotation regions; do not use an optional tight mask to replace the panel
  crop automatically.
- **[Existing callers expect SAM provenance]** → Keep the segmentation source
  field and optional explicit SAM mode, while changing the default source to
  deterministic and updating descriptions/tests.
- **[Scope resolution is lost after recovery]** → Include bounded panel scopes
  in checkpoint layout context and restore them with the existing run state.

## Migration Plan

1. Update the decomposition contract and tests to make deterministic scopes the
   default and SAM explicit-only.
2. Add the panel-scope routing data to Agent layout state and checkpoint
   restoration.
3. Update the four chart sensors and their authorized wrappers to consume the
   resolved scope while preserving existing direct source-image behavior when
   no panel is supplied.
4. Update runtime prompt and tool descriptions to describe VLM bbox plus
   deterministic scope generation, not mandatory SAM refinement.
5. Run focused dashboard tests, the full Python suite, and the frontend smoke
   checks. Validate the real multi-panel fixture with two bar sensors and one
   pie sensor before considering the change complete.

## Open Questions

无。Derived crop persistence is intentionally deferred; the current change
uses source attachment plus a bounded internal ROI as the sensor input.
