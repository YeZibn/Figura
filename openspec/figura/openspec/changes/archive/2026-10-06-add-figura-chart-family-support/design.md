## Context

The current `src/figura` implementation has a narrow four-family contract. `charts/chartspec/` stores one generic point shape for bar, line, scatter, and pie; `charts/chartfigure/rendering.py` branches on those four types. `tools/implementations/` registers four public measurement tools, while `agent/execution_state.py`, `agent/execution_resources.py`, `agent/prompting/observations.py`, `tools/measurements/visualization.py`, `tools/implementations/assemble_chart_figure.py`, and the Gateway timeline each recognize those tool names. The source authorization and observation-scope path is already shared through the Run resource catalog and Sources services.

The deployment boundary is the `figura` implementation and its OpenSpec store. The separate `chartagent` implementation and store are outside this change. Run facts and managed render files already have durable storage; this design does not add tables or reinterpret persisted legacy facts.

## Goals / Non-Goals

**Goals:**

- Define one observable measurement call and one typed result union for the ten selected families.
- Make ChartSpec v2, ChartFigure v2, assembly, and rendering agree on the same closed set of family-specific datasets.
- Keep source authorization, pixel coordinates, uncertainty, and Run evidence references intact across tool execution and resource projection.
- Make rollout and rollback behavior explicit for the intentionally incompatible Registry and content contracts.

**Non-Goals:**

- Add a hidden image classifier, nested Provider request, automatic chart-family switching, or automatic measurement retry.
- Turn measurement observations directly into ChartSpec data or claim that a measurement reference verifies every authored value.
- Support combo/multi-axis, 3D, candlestick, funnel, rose, or other specialist families.
- Parse, convert, adapt, backfill, or execute old tool/result/ChartSpec/Figure contracts in the new Registry.
- Add a database migration, new persistence subsystem, or changes to the `chartagent` store.

## Decisions

### 1. One model-facing measurement tool, with a required family discriminator

`measure_chart` is the only public measurement definition in the new Registry. Its input has exactly `source_kind`, `source_id`, `chart_type`, and optional `observation_scope`. It resolves the source through the existing Run resource catalog and Sources ownership checks, applies the existing normalized include/exclude scope semantics, then dispatches on the required `chart_type` to an internal family adapter.

The tool definition/router belongs under `tools/implementations/measure_chart.py`. Shared source resolution, scope validation, pixel-coordinate rules, confidence, warnings, and result bounds belong in shared measurement contracts. Family algorithms belong under `tools/measurements/`; each adapter returns its own closed observation type inside the common v2 envelope. The model-facing JSON Schema and ToolDefinition expose only `measure_chart`. The four current algorithm cores may be reused after refactoring them to the new internal adapter/result contract; the old `measure_bars`, `measure_lines`, `measure_scatter`, and `measure_pie` ToolDefinitions and old result serializers are removed rather than wrapped.

This keeps the tool lifecycle, evidence annotation, errors, and resource identity uniform while allowing algorithms to remain specialized. Keeping four public tools would continue to make prompt, Registry, timeline, and assembly behavior branch on chart family. A single generic vision detector was also rejected: families have different geometry and calibration semantics and should not be forced through one detector.

### 2. The Agent owns recognition and follow-up decisions

The Agent chooses one of the ten values from the user's description, an already available visual observation, or a successful `load_image` observation. When visual classification is still uncertain, the Agent loads the original image and chooses after it is included in a later Provider request. A direct measurement call does not require `load_image` when the requested family is already known.

The tool never invokes a Provider or classifier and never changes `chart_type`. A family mismatch produces `unsupported` or another honest bounded observation. The Agent may then inspect the image or choose a different explicit family call. Partial results, warnings, and failures do not cause an automatic repeat. This preserves a visible Run trace and avoids consuming hidden Provider work.

### 3. Measurement uses a shared envelope and family-specific sensors

The common v2 result envelope contains the requested family and authorized source identity, source dimensions and coordinate frame, status, nullable plot rectangle, typed `observations`, four confidence dimensions, warnings, and a `truncated` flag. Pixel coordinates stay in the full Attachment or Panel frame even when a scope is applied. A scoped sensor may see only the effective mask; it must not reinterpret that mask as the plot boundary or silently expand an invalid/empty scope.

The shared pipeline is:

1. Resolve the exact Attachment or Panel from the target Run's authorized resource catalog and verify Session ownership through Sources before reading bytes.
2. Decode the selected image and apply the validated effective observation mask without changing the published coordinate origin.
3. Route only to the family named in the call. Family sensors may share image preparation, OCR, color, contour, axis, and calibration utilities, but they retain family-specific geometry and association rules.
4. Validate the closed family observation, enforce existing shared collection/text/pixel bounds, set `truncated` if candidates were omitted at a bound, and emit bounded warnings rather than an unbounded result.
5. Let the existing durable Run boundary commit the call/result facts. Annotated-image reconstruction recognizes the single `measure_chart` name and uses its `chart_type` to draw the appropriate evidence overlay.

The first sensor design is deliberately evidence-first:

| Family | Sensor focus | Evidence it may return |
| --- | --- | --- |
| Bar | Plot bounds, categorical axis, baseline, bar rectangles, color/group association | Bar polygons and pixel lengths; calibrated values only when ticks and baseline support them |
| Line | Axis/tick detection and color-separated traces | Separate polylines and sampled/marked points; preserve breaks instead of connecting occluded segments |
| Scatter/bubble | Marker candidates and color/series association | Visible centers and radii; flag merged, dense, occluded, or overlapping marks without estimating hidden counts |
| Pie/donut | Center, outer/inner radius, sector boundaries and angular coverage | Ordered start/sweep angles and ratios only when coverage supports them |
| Area | Filled-region boundaries and lower/baseline edges | Separate series polygons or boundary traces; preserve gaps and avoid relabeling an unfilled line as an area |
| Histogram | Numeric plot axis, adjacent bin edges, and bar extents | Ordered numeric intervals and counts; do not turn bins into categorical bars |
| Box plot | Box edges, quartile/median marks, whiskers/caps, and explicit outlier marks | Pixel positions with nullable axis values; do not infer outliers from a statistical rule that is not visible |
| Radar | Center, spokes, grid rings, labels, and series boundaries | Ordered dimension vertices and radial calibration when visible tick evidence exists |
| Heatmap | Grid segmentation, row/column association, cell color, and optional colorbar | Cell bounds/color always when visible; numeric cell values only with a supported color-scale calibration |
| Treemap | Rectangle segmentation, labels, containment hierarchy, and relative area | Visible bounds and area ratio; explicit values only when legible or otherwise directly supported |

The exact result requirements are in `specs/chart-family-measurement/spec.md`. No sensor claims a value merely because a shape exists. Geometry can remain useful when calibration, OCR association, or family structure is incomplete; those conditions produce null values, `partial` status, and warnings. Measurement output is candidate evidence, not a write-through to ChartSpec.

### 4. ChartSpec v2 is a closed discriminated union

`charts/chartspec/` becomes the sole owner of immutable ChartSpec v2 models, strict codecs, canonical serialization, semantic validation, and bounded issues. Its top-level value is `schema_version`, `metadata`, `coordinate_system`, and `dataset`. `metadata.chart_type` selects one closed dataset branch; `coordinate_system.kind` selects the coordinate contract. Cartesian axes explicitly declare categorical, numeric, or time coordinates; radar declares a polar value range; matrix, hierarchy, and pie use their corresponding non-Cartesian forms. The exact data fields and semantic rules are recorded in `specs/chart-spec-core/spec.md`.

Parsing rejects duplicate keys, unknown fields, type coercion, non-finite values, invalid family/coordinate combinations, and content outside the existing byte/item/text bounds. Semantic validation is deterministic and side-effect free. It does not read image evidence, Runs, files, or Providers. Canonical serialization preserves meaningful list order and normalizes only documented defaults. There is no v1 branch, fallback, or converter.

The current per-ChartSpec serialized bound remains 256 KiB and each ordered collection remains bounded at 512 items. ChartFigure's existing 64 KiB whole-object limit is stricter for assembled content; a ChartSpec that is valid alone but cannot fit in a Figure is rejected at Figure validation. The design does not split a Figure across storage or relax either bound.

Alternative considered: retain generic points and infer family semantics in the renderer. Rejected because histogram bins, box summaries, matrix cells, polar dimensions, and tree nodes have different invariants that a generic point cannot validate safely.

### 5. ChartFigure v2 keeps Figure identity and evidence references outside chart data

`charts/chartfigure/` owns ChartFigure v2 parsing, canonical digest, and Figure validation. A Figure contains one to four ordered ChartSpec v2 children, a one- or two-column layout, and optional `measurement_refs` per child. Every supplied reference must resolve to a successful committed `measure_chart` call in the same Session and authorized Run prefix. Empty references remain valid and mean no evidence was selected. A reference does not assert value-by-value agreement.

`assemble_chart_figure` accepts only the complete v2 Figure and validates it without repair, rendering, or separate storage. The existing durable fact remains the source of Figure content and digest. The Figure does not absorb Run identity, authorization, storage paths, review/publication state, or image bytes.

### 6. One fixed renderer dispatches to ten family renderers

The public `render_chart_figure` contract and `(run_id, call_id)` artifact identity remain stable. Internally, the renderer dispatches each validated child to a family renderer, then uses the shared bounded canvas/layout engine to honor child order and `layout.columns`. Bubble size uses the supplied size channel; donut uses its positive inner radius. Palette, fonts, dimensions, label policy, and spacing remain server-controlled.

Each child renderer derives display ranges from valid content and does not invent units or labels. Bubble `size` maps linearly to marker area within the renderer's fixed minimum/maximum marker-area policy; equal size values render equally. Heatmap numeric cells use one linear color scale over the non-null values with a visible scale legend; null cells use a distinct neutral fill. Treemap uses a deterministic squarified layout, descending positive weight, and original dataset order as the stable tie-break. Radar rings derive from the declared polar range. Histogram bars use the supplied bin `value` and declared measure; box-plot outliers are rendered only from the explicit `outliers` array. Shared layout reserves space for Figure/child titles and existing source/note text. If a label, legend, or caption cannot fit without clipping or overlap, rendering returns the existing bounded failure contract. PNG bytes remain private managed storage, integrity checks and idempotent local writes remain owned by the existing render path, and only committed successful results appear as `chart_render` resources. These persistence rules already exist in the main rendering/resource specifications and are not duplicated as new requirements here.

Separate public render tools, model-supplied style/dimension parameters, and automatic layout repair were rejected because they fragment Figure behavior or make output non-deterministic.

### 7. Migrate every consumer to the one new contract

The Registry version advances from `figura-web-v8` to `figura-web-v9`. Its ordered tool list removes the four old measurement definitions and registers `measure_chart`. The following consumers must be migrated in the same release before v9 can accept Runs:

- Bootstrap and tool descriptions/native schemas.
- Agent execution-state result schemas and `RunExecutionState.resources` typed measurement resources.
- Prompt projection and workflow guidance for selecting a family, using `load_image` when unclear, and treating measurements as evidence.
- Annotated-image reconstruction and the measurement visualization dispatch.
- Assembly reference resolution, which accepts successful `measure_chart` facts only.
- Gateway timeline labels and structured measurement summaries, based on the family discriminator rather than old tool names.
- Tests, fixtures, architecture/tool documentation, and examples.

Old Run facts stay in durable storage, but the v9 resource projector does not reinterpret old tool results as `measure_chart`, does not convert v1 Figure/ChartSpec content, and does not expose those items as v2 typed measurement/Figure resources. No data backfill or compatibility executor is introduced. Generic raw Run history remains governed by its existing contracts; this change adds no promise to semantically reconstruct old chart artifacts.

Alternative considered: register the new tool alongside old tools and phase out old calls later. Rejected because it leaves two public contracts, expands Registry state, and requires precisely the compatibility path the change excludes.

## Risks / Trade-offs

- **Six families have no existing sensor core** → Implement them as first-class family adapters and require family-specific synthetic/curated fixtures before enabling v9; do not ship a partial family set behind the advertised ten-family enum.
- **Visual ambiguity can produce confident-looking wrong readings** → Keep geometry, calibration, and association confidence separate; use null values and warnings; do not silently switch family or claim hidden counts.
- **The ten-family ChartSpec union is larger than the current model** → Keep parsing/semantic validation in the Charts owner, cap ordered collections and serialized payloads, and use one branch per family rather than a generic extensible object.
- **Strict v2 schemas reject stored v1 chart content** → Do not backfill or down-convert; communicate the clean break and make cutover/rollback one-way after v2 facts are written.
- **Registry cutover during an active old Run would strand work** → Require all v8 Runs to be terminal before activating v9; the existing prior-Registry unresolved-call policy remains in force.
- **A valid child may exceed the stricter Figure byte cap** → Reject at Figure validation with a bounded size issue; do not truncate data or split the Figure.
- **Provider tool-schema support may differ for a large nested union** → Keep runtime parsing/validation authoritative and test the emitted `ToolDefinition` against each configured Provider's supported schema subset; reduce only descriptive schema complexity, never the runtime contract.
- **Render labels may not fit for dense data** → Return a bounded render failure instead of clipping; test all families in single- and multi-child layouts.

## Migration Plan

1. Implement and test the complete v2 content, measurement, assembly, resource projection, annotation, prompt, timeline, and rendering path. The ten chart families are one release scope; v9 is not enabled while any advertised family is only a placeholder.
2. Before deployment, verify that every Run bound to `figura-web-v8` is terminal. Do not activate v9 while any old Registry Run can still resume.
3. Activate the v9 Registry as a clean cutover. Do not register v8 aliases, old ToolDefinitions, old result decoders, v1 ChartSpec/Figure parsers, or an old Registry executor.
4. After activation, verify a fresh Run for each measurement family, v2 assembly with and without references, a mixed-family Figure render, resource projection, annotated-image feedback, and recovery of a committed v9 call.
5. Rollback to v8 is allowed only before v9 has committed any new Run facts. Once v2 facts exist, use a forward fix or another v2-compatible release; do not run a v8 binary against v2 chart facts or attempt a down-conversion. This follows directly from excluding the compatibility layer.

There is no database migration or backfill. Existing raw Run facts remain untouched. Old facts are not upgraded into the new typed resource catalog.
