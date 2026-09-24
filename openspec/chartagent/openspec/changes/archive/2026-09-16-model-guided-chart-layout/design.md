## Context

See `proposal.md` for the motivation. The current chart observation layer uses
deterministic pixel heuristics to discover a frame before extracting marks.
The recent real Gateway run showed that a light-gray Y axis was missed, dark
text was fitted as a diagonal axis, date labels could not provide numeric X
ticks, and a markerless trace produced many density-based pseudo-points. The
same run also produced a tool-result event larger than the Gateway event limit,
which replaced the outer tool identity and confused the desktop timeline.

The Agent already has a multimodal image-loading path and all four chart
observation tools share source-image evidence and coordinate infrastructure.
The design must preserve attachment authorization, source-image coordinates,
bounded visual observations, and free semantic planning after layout context
is available.

## Goals / Non-Goals

**Goals:**

- Establish one reusable `ChartLayoutContext` for plot, axis, tick, legend, and
  annotation regions across bar, line, scatter, and pie observations.
- Let the model resolve semantic region roles while deterministic code validates
  geometry and performs pixel measurement.
- Keep frame geometry separate from surrounding text so rotated labels and
  annotations cannot become axes or marks.
- Support ordered date/categorical X evidence and markerless line traces without
  fabricating semantic points.
- Preserve tool identity when diagnostic event bodies are bounded or truncated.
- Keep the existing attachment and visual-observation security boundary intact.

**Non-Goals:**

- Do not ask the model to replace pixel-level bar, line, scatter, or pie
  measurement.
- Do not infer exact dates, chart values, or financial meaning solely from a
  layout hint.
- Do not require a fixed order of all four chart sensors for every user query.
- Do not introduce a new chart rendering system or change generated-chart
  publication and review semantics.

## Decisions

### 1. Use a model-proposed, validated layout context

The layout preflight produces a structured context with source image dimensions,
orientation, coordinate-model hint, and normalized role regions. It is an
advisory object identified by a bounded context ID and associated with the
authorized attachment/run. The model can recognize that a region is a plot,
legend, or rotated tick band even when its pixels are light or semantically
ambiguous; it does not own final calibration.

Alternatives considered:

- **Pure pixel detection:** rejected because it already confuses light axes and
  dark labels on the real attachment.
- **Model returns every data point:** rejected because approximate pixel
  coordinates and numeric transcription are less reliable than deterministic
  evidence plus OCR validation.
- **One strict crop only:** rejected because data labels and axis labels may sit
  outside the plot frame.

### 2. Validate layout hints with independent evidence

The validator maps normalized regions into source pixels and checks bounds,
minimum size, axis placement, expected axis relationship, colored-trace
coverage, and conflict with obvious image boundaries. A hint can be accepted,
accepted with warnings, or rejected. Rejection must leave pixel evidence
available and must not invent an alternative complete transform.

The shared context exposes two related but separate areas:

- `measurement_frame`: the region used for coordinate and mark geometry.
- `annotation_regions`: title, legend, tick-label, and data-label regions used
  for semantic association and cross-checking.

This prevents the line sensor from tracing legend swatches while preserving
labels that overflow the frame.

### 3. Run layout preflight once and reuse it

When chart analysis needs geometry, the Agent obtains the layout context after
loading the authorized image and before the specialized sensor. The context is
passed as bounded structured evidence, not as a local path or an image byte
copy. Bar, line, scatter, and pie tools may accept it independently; the Agent
is still free to invoke only the tools relevant to the question.

The existing sensor-only path remains supported for compatibility and uses the
validator's deterministic fallback. A sensor must report when it did not have
an accepted context.

### 4. Treat sampling mode as explicit line evidence

Line extraction first determines whether compact, isolated marker evidence
exists. If not, it samples only at validated numeric/date/category anchors or
preserves the continuous trace without confirmed points. Date/category text is
kept as ordered positional evidence; semantic numeric X values require a
separate reliable mapping.

OCR remains useful for labels and values, but its output is associated through
the annotation regions and checked against trace geometry. It is not allowed to
turn a dense trace into a claimed point count.

### 5. Preserve protocol identity outside bounded result bodies

The Gateway event envelope keeps `tool_name`, `call_id`, `status`, run ID, and
sequence metadata outside the bounded diagnostic result. A large trace result
is summarized or marked truncated under `result`, while the frontend continues
to reconcile the call and result by the same call ID. The client also renders a
bounded indicator instead of treating a truncated body as a new tool.

This keeps event size limits without sacrificing the execution model's identity
contract.

### 6. Reuse validation and evidence across chart types without coupling marks

The layout context and validator live in the shared observation foundation.
Each chart detector keeps its own mark semantics: bars and baselines, line
traces and anchors, scatter markers, or pie sectors. No detector calls another
detector's private extraction routine, and the layout preflight does not force
all chart tools to run.

### 7. Register layout preflight through the regular chart-tool catalog

`inspect_chart_layout` is part of `CHART_TOOLS` and uses the same authorized
attachment adapter as the other image-based chart tools. This makes its public
model contract consistently use `attachment_id` and prevents the Gateway from
registering a second copy of the tool beside the catalog. The old optional
registration toggle is removed because the catalog is the single registration
source.

The model-facing description remains a bounded English selection contract. The
frontend and execution trace obtain the Chinese label from the shared tool
presentation catalog, so local-language UI metadata does not leak into or
replace the model description.

## Risks / Trade-offs

- **Model layout coordinates can be imprecise** → Use normalized coordinates,
  deterministic validation, bounded confidence, and a fallback that preserves
  pixel evidence.
- **One extra model turn increases latency and cost** → Run it once per
  attachment/run and reuse the context; skip it for non-geometric questions.
- **Annotation regions may overlap the measurement frame** → Keep role labels
  and inclusion/exclusion decisions explicit instead of relying on a single
  crop rectangle.
- **Date/category anchors still may not map to exact semantic dates** → Preserve
  ordered labels and pixel positions, emit no numeric X values without a
  declared mapping, and surface the limitation.
- **Large trace data can still exceed UI detail limits** → Bound only the
  diagnostic body, retain event identity, and expose a truncated-state marker.
- **Existing sensor-only callers may produce different frame choices** → Keep
  the compatibility path, add real-image regression coverage, and compare
  accepted layout confidence with the fallback result during migration.

## Migration Plan

1. Add the layout context contract and validator without changing existing
   sensor call signatures.
2. Integrate layout preflight into Agent chart-analysis runs and pass accepted
   context to specialized sensors.
3. Update line and Cartesian sensors to use role regions, date/category anchors,
   and explicit markerless sampling.
4. Update Gateway event bounding and frontend timeline reconciliation while
   retaining compatibility with old truncated events.
5. Validate the attached double-series line chart, rotated-label fixtures,
   horizontal/rotated charts, and existing bar/pie/scatter suites.

Rollback consists of disabling layout preflight and using the existing sensor
  fallback; event-envelope changes remain backward-compatible because they add
  outer identity fields without changing attachment IDs or preview resources.
