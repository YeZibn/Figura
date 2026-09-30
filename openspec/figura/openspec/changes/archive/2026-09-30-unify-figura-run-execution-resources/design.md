## Context

See `proposal.md` for the motivation and bounded scope. The current `RunExecutionState` is an Agent-owned projection, but exposes six unrelated top-level collections. Its builder combines Run inputs and committed tool facts with Sources metadata; OCR and measurements are projected differently, accepted Figures are summaries, and image bytes are resolved through several separate paths. Runtime already persists complete tool calls, attempts, and results. Sources already owns Attachment and Panel metadata/files and private render PNGs. These owners remain authoritative.

The target Run is assembled from terminal earlier Run states plus a supplied current `RunState` prefix. A Session snapshot can contain facts newer than that prefix, so it may provide metadata but must not advance the target Run's visible resources. The resource view is reconstructed on demand and is not itself a persistence boundary.

## Goals / Non-Goals

**Goals:**

- Make the typed resource catalog the only RunExecutionState data interface for Attachments, Panels, OCR, measurements, Figures, and renders.
- Preserve the complete existing domain data and committed outcomes while keeping IDs, image bytes, paths, and persistence in their current owners.
- Make authorization, prefix selection, lookup, and image recall use one catalog boundary.
- Migrate all internal consumers directly and remove obsolete collection projections and special lookup paths.

**Non-Goals:**

- Add a database table, durable resource snapshot, Run field, resource cache, or new identifier.
- Change tool argument/result schemas, HTTP/SSE payloads, ChartSpec/ChartFigure schemas, Provider behavior, or user-visible recovery behavior.
- Add a model-callable generic resource-inspection tool. Existing tools continue to perform the same actions and use typed catalog lookup internally.
- Rebuild session-level Panel listing semantics or change which prior Runs enter complete conversation history.
- Edit implementation overview documents in this proposal change; documentation synchronization remains a separate requested workflow.

## Decisions

### 1. Use one immutable catalog and discriminated typed references

`RunExecutionState` has exactly two data fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `run_id` | `str` | Target Run whose current committed prefix bounds this view. |
| `resources` | ordered tuple of `ExecutionResource` | Every eligible Attachment, Panel, OCR result, measurement, accepted Figure, and render result in the target Run plus eligible same-Session history. |

Every `ExecutionResource` has exactly two data fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `ref` | `ResourceRef` | Stable typed identity for lookup and cross-resource references. |
| `content` | `ResourceContent` | Complete immutable content for that reference. |

`ResourceRef` is a closed union. `ImageResourceRef` has `kind: "attachment" | "panel"` and `id: str`. `ToolResourceRef` has `kind: "ocr" | "measurement" | "chart_figure" | "chart_render"`, `run_id: str`, and `call_id: str`. The reference's `kind` selects the content variant; there is no third `kind` field on the resource envelope. Tool references include the originating Run because call IDs are only logical-call identifiers and may be reused in another Run. Attachment and Panel IDs remain opaque.

The catalog exposes ordered `list(kind=None)` and exact `get(ref)` operations. Filtering preserves catalog order. A missing reference produces the existing bounded not-found failure; it never falls back to another Run, resource kind, or Session. The models are frozen and nested mappings/sequences are immutable. There is no mutable “active image” or side index that can diverge from `resources`.

**Alternative considered:** Keep six named accessors and add a combined list facade. Rejected because consumers would still depend on the six old interfaces and there would be two sources of truth. The migration removes the six fields and their special reads in the same change.

### 2. Keep resource content complete but put IDs in references once

The following are the exact content variants and fields. The IDs listed in `ref` are intentionally omitted from `content` unless they identify a different owner fact.

| Content variant | Fields |
| --- | --- |
| `AttachmentContent` | `session_id`, `filename`, `media_type`, `byte_count`, `created_at` |
| `PanelContent` | `session_id`, originating `run_id`, `source_attachment_id`, `name`, complete `points` (`tuple[PanelPoint, ...]`, each with normalized integer `x` and `y`) |
| `OcrContent` | `attempt_id`, nullable typed `source_ref`, nullable immutable `observation_scope`, `outcome`, and exactly one of complete bounded `result` or structured `error` |
| `MeasurementContent` | `attempt_id`, `tool_name`, nullable typed `source_ref`, nullable immutable `observation_scope`, `outcome`, and exactly one of complete bounded `result` or structured `error` |
| `ChartFigureContent` | `attempt_id`, `outcome`, and exactly one of a success `result` (`figure: ChartFigure`, `figure_digest: str`) or structured `error` |
| `ChartRenderContent` | `attempt_id`, nullable typed `figure_ref`, `outcome`, and exactly one of bounded render metadata `result` or structured `error` |

`OcrContent.result` preserves the existing result schema without renaming: `source_kind`, `source_id`, `image_size.width`, `image_size.height`, `coordinate_system`, `available`, `truncated`, and every `snippets[]` entry's `snippet_id`, `text`, `bbox_px`, and `confidence`. It does not crop, truncate further, recompute, or summarize the committed OCR result.

`MeasurementContent.result` preserves the complete current result schema for its named tool without renaming fields. The common Cartesian fields are `source_kind`, `source_id`, `image_size {width, height}`, `coordinate_system`, `status`, nullable `plot_area_px {x, y, width, height}`, `axes {x, y}`, `confidence {overall, geometry, calibration, association}`, and `warnings[]`. Each axis has `kind`, nullable `label_text`, nullable `label_confidence`, nullable `points_px`, `ticks[]`, and nullable `calibration`; each tick has `id`, `text`, nullable `value`, `bbox_px`, `point_px`, and `confidence`; calibration has `slope`, `intercept`, `residual_value`, `support_count`, `support_span_px`, `confidence`, and `calibrated`.

Tool-specific result fields remain:

- `measure_bars`: `orientation`, `bar_mode`, nullable `baseline`, `series[]`, and `bars[]`. Baseline contains `points_px`, `axis`, `slope`, `intercept`, `residual_px`, and `confidence`. A series contains `id`, `color`, nullable `label`, and nullable `label_confidence`. Each bar contains `id`, `category_index`, nullable `category_label`, nullable `category_tick_id`, `series_id`, `geometry {bbox_px, polygon_px}`, `measure {value_length_px, ratio_to_shortest, value}`, and nullable `stack {segment_index, total_length_px, total_geometry, total_value}`.
- `measure_lines`: `series[]`; each series contains `id`, `color`, nullable `label`, nullable `label_confidence`, `trace[]`, and `points[]`. Each point contains `id`, `position_px`, nullable `x_value`, nullable `y_value`, nullable `x_tick_id`, nullable `x_category_label`, `source`, and `confidence`.
- `measure_scatter`: `series[]`; each series contains `id`, `color`, nullable `label`, nullable `label_confidence`, and `points[]`. Each point contains `id`, `position_px`, nullable `x_value`, nullable `y_value`, nullable `x_tick_id`, nullable `y_tick_id`, nullable `radius_px`, `confidence`, and `flags[]`.
- `measure_pie`: `plot_region` (nullable `{center_px, radius_px}`), `sectors[]`, `confidence {overall, geometry, segmentation, association}`, and `warnings[]`. Each sector contains `id`, `start_angle_deg`, `sweep_angle_deg`, nullable `ratio`, nullable `color`, nullable `label_text`, nullable `label_confidence`, and `confidence`. Its common source identity, image size, coordinate system, and status retain the same meanings as current tool results.

`observation_scope` is the exact normalized `include`/`exclude` polygon value supplied to that logical call; omitted scope is `null` and means the complete selected source. Failed calls retain a structurally valid supplied scope; absent or invalid scope on a failed call is `null` and does not claim full-image coverage.

`ChartFigureContent.result.figure` is the complete existing immutable Figure: `schema_version`, `title`, `layout.columns`, ordered `charts[]`, each `chart_id`, full `chart_spec: ChartSpecData`, and `measurement_refs[]`. `figure_digest` must match the accepted result fact. The resource does not replace or reshape embedded Figure fields.

Successful `ChartRenderContent.result` retains exactly the existing metadata: `figure_digest`, `image_sha256`, `media_type`, `byte_count`, `width`, and `height`. Its `figure_ref` points to a `chart_figure` resource. The PNG remains in private Sources storage. `error` preserves the existing safe `ToolExecutionError` fields (`code`, `message`, `retryable`, nullable `field_path`). For each outcome, the result/error exclusive-or invariant is checked during construction.

No resource includes a duplicate originating `run_id`/`call_id` when these are already in its `ToolResourceRef`. Existing nested result identity fields remain untouched because they are part of the committed tool result contract and are validated against the reference.

**Alternative considered:** Store only a normalized generic JSON object or retain Figure summaries. Rejected because consumers would lose type guarantees and complete evidence/ChartSpec data; the goal is a typed catalog, not a lossy index.

### 3. Reconstruct each resource from its current authoritative owner and one Run prefix

`RunExecutionStateService` continues to receive the target `RunState` and earlier terminal Run states. It validates that prior Runs are contiguous, terminal, earlier, and from the same Session. Those supplied states are authoritative for tool calls, attempts, results, and Run inputs. A Session snapshot can resolve Sources metadata and verify ownership, but current or later Run facts from that snapshot are never candidates for the target catalog.

Reconstruction rules:

1. Read the immutable `RunInput` from each eligible Run. Add each referenced Attachment once, in first-reference order, only after Sources confirms its Session owner and metadata.
2. Inspect committed tool calls/results from eligible Run states. A Panel is included only after a successful decomposition result is committed and every returned Panel record matches that result and Session.
3. Create one OCR or measurement resource per committed logical call/result pair. Associate the matching attempt and tool call, validate tool name, source identity, scope shape, outcome, and full result against the existing result schema. Repeated scans stay separate resources.
4. Reconstruct each successful ChartFigure from the persisted `assemble_chart_figure` call arguments, parse and validate the complete existing Figure, and compare the canonical digest with the committed successful result. A failed assembly uses only its committed structured error.
5. Create one ChartRender resource per committed render call/result. Validate the call's Figure reference against an accepted Figure resource; verify its committed metadata against the private PNG when the PNG is read.
6. Omit started attempts without a committed outcome. Keep committed safe failures queryable even when their source is malformed, but set an invalid/unparseable `source_ref` to `null` and never grant it image access.

Ordering is deterministic. Attachments are first, in first-reference order across Run ordinals and input attachment order. Remaining resources are ordered by originating Run ordinal, persisted tool-call sequence, call position, and result-item position for multi-Panel results. Kind-filtered listing preserves this order. Duplicate typed references, mismatched attempts, malformed successful results, mismatched Panel facts, or invalid Figure digest fail state construction; the builder never repairs or silently drops a committed success.

**Alternative considered:** Build from the latest full Session snapshot and filter only by `run_id`. Rejected because a partially supplied current Run prefix must not expose later committed facts. **Alternative considered:** Write a new resources table to simplify reads. Rejected because Runtime and Sources already own the facts and no durability gap requires another store.

### 4. Put all image reads behind the catalog, with no implicit rendering

Add one Agent-owned image reader that accepts the target Session/catalog and a typed `ResourceRef`. It returns only the existing transient image bytes and dimensions needed by current consumers; it does not persist or add fields to tool results.

| Reference kind | Image-read behavior |
| --- | --- |
| `attachment` | Verify the ref exists in the target catalog, then use the Attachment owner to resolve and validate bytes in the same Session. |
| `panel` | Verify the ref exists in the target catalog, then use the Panel owner to resolve and validate bytes in the same Session. |
| `ocr` / `measurement` | Require a successful resource and authorized image `source_ref`; reconstruct the existing deterministic annotation in memory from source bytes and the full committed result. |
| `chart_render` | Require success; read the existing private PNG and verify SHA-256, media type, byte count, format, dimensions, and Provider limits against the committed result. |
| `chart_figure` | Return a bounded “explicit render required” failure. Never invoke the render tool implicitly. |

Any unknown, cross-Session, out-of-prefix, failed, non-image, missing, unreadable, corrupted, or metadata-mismatched reference fails with a bounded error and no replacement bytes. Provider request assembly completes all necessary reads, annotation rendering, PNG integrity checks, and image count/size checks before claiming the Provider attempt. `load_image` continues to expose its current tool contract and remains the model's explicit original-image action; it resolves the source through the same catalog and reader. A generic model-callable `read_resource` tool is not added.

**Alternative considered:** Let each tool and request builder resolve Sources directly. Rejected because authorization and corruption checks would remain inconsistent across call paths. **Alternative considered:** Treat an accepted Figure as an image source and render during read. Rejected because rendering is an explicit tool effect with a persisted result and must remain visible in tool history.

### 5. Preserve Memory history and keep the prompt index concise

The complete ordered assistant/tool interaction remains the request's source for historical result payloads. Resource inventory is derived from the catalog and supplies addresses and concise labels, not a second copy of OCR/measurement/Figure/render JSON. It lists Attachment/Panel IDs and names; OCR/measurement typed refs with source and outcome; Figure refs with title and chart summary; and render refs with Figure ref and outcome. Complete resource content remains available to internal consumers through `get(ref)` and complete tool results remain in Memory. No new prompt message type or public protocol field is added.

Image blocks remain limited to the immediately preceding fully committed tool batch: successful explicit `load_image` source bytes, successful OCR/measurement annotation images, and successful render PNGs, each once under current call-order rules. Older Run and older batch image bytes are never replayed. All image reads use the same catalog/prefix authorization and complete before provider-attempt claim.

**Alternative considered:** Insert full resources into a new prompt layer. Rejected because committed ToolMessages already preserve full results; duplicating them would inflate requests and weaken the one-history rule.

### 6. Migrate owners directly and remove obsolete projections

Keep the existing module layout and use three focused Agent modules:

- `src/figura/agent/execution_resources.py`: immutable reference/content variants, `ExecutionResource`, and the two-field `RunExecutionState` listing/lookup behavior.
- `src/figura/agent/execution_state.py`: Run-prefix validation and reconstruction of the resource catalog from Runtime facts and Sources records.
- `src/figura/agent/execution_images.py`: common typed image resolution and transient observation/render image reads.

`src/figura/agent/request.py` uses catalog lookup for inventory and latest-batch images. Update `load_image`, OCR/measurement source resolution, Figure assembly/render, and Gateway projections to query typed refs/kinds. Keep existing Session-wide Panel list behavior separate because it is a Session query, not a RunExecutionState resource list.

Remove the old `available_attachments`, `panels`, `ocr_results`, `measurements`, `chart_figures`, and `chart_renders` RunExecutionState fields, their summary/observation-only models where no longer otherwise used, and their old consumer helpers. Delete OCR special read paths once OCR is represented by a catalog resource. Update tests and imports in the same change. No compatibility aliases, adapters, duplicate properties, migration period, or dual read paths are retained.

Gateway's existing public JSON/SSE field names remain unchanged: its projections derive the same summaries from the catalog and continue reading render file bytes through the owning Sources service. No API response expands to include complete OCR, measurement, Figure, image bytes, filesystem paths, or provider continuation.

### 7. Keep persistence and public contracts unchanged

Runtime remains authoritative for committed `ToolCallFact`, `ToolAttemptStartedFact`, and `ToolResultFact`; Memory continues projecting them into complete chronological messages. Sources remains authoritative for Attachment metadata/bytes, Panel records/PNGs, and private render PNGs. Full accepted Figures are reconstituted from persisted assembly call arguments and verified against the result digest. The resource catalog is a read-only projection built per target Run and is discarded after use.

There is no database migration and no changes to Run records/checkpoints, tool schemas/results, HTTP/SSE DTOs, provider message schemas, or image persistence formats. This direct replacement is implemented atomically: consumers and tests move to typed lookup, then the old fields and helper paths are deleted before the change is complete. Rollback is a source-control revert; it does not require data conversion.

## Risks / Trade-offs

- **Full resource materialization holds more complete data in memory than summary projections** → Build only for the requested target Run, retain current OCR/measurement result bounds, avoid a second prompt copy, and keep image bytes transient.
- **A malformed committed success can now prevent catalog construction for its target Run** → Validate before publication and fail closed with the existing bounded integrity error; do not repair persisted history or weaken authorization.
- **Several domains currently read the old six interfaces** → Migrate tools, request assembly, Gateway, and tests in dependency order within one change; remove old names with a repository-wide reference search before completion.
- **A shared image reader can become an oversized abstraction** → Keep it limited to resolving already-typed catalog resources and return the existing byte/dimension values; do not add image caching, generic persistence, or rendering orchestration.
- **Concise resource summaries can drift from full result content** → Derive them from the catalog itself, keep the full ToolMessage authoritative, and test that inventory references resolve and full payloads appear only in history.

## Migration Plan

1. Add typed resource models and catalog reconstruction alongside existing tests, without adding a persisted schema.
2. Add the common image reader and migrate original, OCR/measurement annotation, and render image reads to typed catalog refs.
3. Migrate Figure/measurement tools, request inventory and visual feedback, and Gateway projections. Preserve their current external contracts.
4. Replace old tests/assertions with field-completeness, ordering, prefix, identity, ownership, image integrity/bounds, prompt deduplication, and public-projection regressions.
5. Remove the six old RunExecutionState properties, obsolete summary/projection types, OCR special lookup, and all old consumer code/imports. Search the repository to ensure no callers remain.
6. Run the Figura Python suite under the canonical `agent` Conda environment and `git diff --check`. Do not sync main specs or archive the change as part of implementation; those remain the later OpenSpec workflow.
