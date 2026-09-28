## Context

See `proposal.md` for motivation and `specs/` for the observable contracts. `RunExecutionStateService` currently reconstructs the target Session's authorized Attachment and committed Panel inventory from Run inputs and durable tool facts. `AgentRequestBuilder` already projects committed tool results into conversation history. Tool handlers receive a call-scoped `ToolContext`, and successful results are persisted by the existing durable tool-execution path as bounded JSON.

The legacy ChartAgent bar sensor provides reusable geometry-detection behavior, but its public adapter accepts a local `image_path` and returns a `ToolResult` that may contain generated overlay images. Figura's handler contract instead uses opaque source IDs and a JSON-only result.

## Goals / Non-Goals

**Goals:**

- Let the model measure a whole authorized Attachment or an isolated authorized Panel with one source-ID contract.
- Keep source authorization, image resolution, pixel-coordinate labeling, and tool-result persistence within Figura's existing boundaries.
- Rebuild measurement observations in `RunExecutionState` from committed execution facts without adding another persisted state owner.
- Preserve geometry and uncertainty while leaving evidence selection with the Agent.

**Non-Goals:**

- OCR of category names, legends, or numeric ticks; conversion to chart-unit values; region-targeted remeasurement; or evidence-ref targeting.
- Frontend or Gateway measurement endpoints, visual overlays, a measurement database/table, or a `MeasurementSession` store.
- Line, scatter, or pie sensors; these remain separate future changes.

## Decisions

### 1. Use the existing source identity contract for both image kinds

The model-facing parameters are exactly `source_kind` (`attachment` or `panel`) and `source_id`, matching `load_image`. The handler obtains `RunExecutionState` for the call's Session and Run, checks the ID against `available_attachments` or `panels`, and then resolves bytes through `FiguraAttachmentService` or `FiguraPanelService`. This keeps local paths and byte payloads out of model arguments and avoids a second authorization scheme.

The sensor measures the entire selected image. Attachment measurements use `attachment_px`; Panel measurements use `panel_px`. The tool echoes `source_kind` and `source_id` in its JSON result. A whole Attachment can contain multiple charts; the result remains a full-source candidate, while the model may choose a Panel when isolation is useful. The tool never silently substitutes a Panel or crops a source.

**Alternative considered:** Accept separate optional `attachment_id` and `panel_id` properties. The shared `source_kind`/`source_id` pair matches the existing image tool and makes the selected identity unambiguous.

### 2. Keep the model-facing handler separate from the sensor

Register a focused `measure_bars` definition from a module under `src/figura/tools/implementations/`. Put the image-byte-based bar sensor under `src/figura/tools/measurements/bars.py`. The handler owns schema validation, source authorization, image loading, error mapping, and result construction; the sensor owns chart geometry detection and returns plain JSON-compatible data.

Adapt the legacy sensor's geometry and baseline logic to accept image bytes or a decoded image. Do not import its path-based tool adapter, `ToolResult`, `GeneratedImage`, or overlay renderer. This follows Figura's current handler contract and keeps image bytes out of durable result facts.

The initial sensor handles single, grouped, and stacked two-dimensional bars with vertical or horizontal orientation. It may report a slightly oblique baseline as `oblique`. It does not run OCR or produce semantic category, series, or axis labels.

### 3. Return source-coordinate geometry and honest pixel measurements

The successful result has the fields defined by `bar-chart-measurement`: source identity, image size, coordinate system, status, orientation, bar mode, plot area, baseline, series, bars, confidence, and warnings. Bar geometry uses `[x, y, width, height]` bounding boxes and four-corner polygons in the selected source's pixel space. Baselines carry their fitted points and residual/confidence values. A bar's `value_length_px` is signed relative to its detected baseline. `ratio_to_shortest` is the absolute pixel length divided by the shortest valid detected bar length.

When a reliable baseline is unavailable, retain bar geometry but return null pixel lengths and ratios. Do not infer values in chart units without numeric axis calibration. A readable image with no bars, partial evidence, or unsupported perspective returns a successful observation status and warnings; source authorization and image-read failures use the existing bounded tool-error contract.

`measure_bars` returns only JSON. A later visual overlay requires a separately defined artifact/image-result contract and is not smuggled into this tool result.

**Alternative considered:** Port the legacy result envelope, evidence-ref index, per-source measurement session, and overlay bundle. Figura already persists call/attempt/result identity, and the first bar slice has no targeted remeasurement consumer for that extra state.

### 4. Derive RunExecutionState measurements from committed facts

Add a frozen `MeasurementObservation` projection to `src/figura/agent/execution_state.py` and add `measurements` to `RunExecutionState`. Each observation contains `run_id`, `call_id`, `attempt_id`, `tool_name`, `source_kind`, `source_id`, `outcome`, and exactly one of `result` or `error`. Build the tuple by matching each `measure_bars` `ToolCallFact` to its committed `ToolResultFact` in the Session snapshot, validating its source against the reconstructed Attachment/Panel inventory, and ordering by Run ordinal then tool-call order.

Include committed successes and failures for valid, authorized sources. Do not include attempts with no committed result, malformed source identities, or sources outside the Session inventory. Retain every committed observation without a second mutable store or an additional measurement retention cap. Existing per-result and per-fact bounds continue to apply.

Do not add `measurements` a second time to the Provider image-inventory message: committed tool outputs already appear as `ToolMessage` entries in Session history. The new field provides a structured runtime projection without duplicating prompt content.

**Alternative considered:** Keep RunExecutionState limited to image inventory and rely only on message history. The structured projection is included because it is the requested intermediate view of measurement outcomes; durable tool facts remain the sole source of truth.

### 5. Register as an additive, read-only replay-safe tool

Compose the definition in `src/figura/bootstrap.py` with the existing execution-state callback and both source services. Mark it `replay_safe`: measuring an image has no local write or external side effect. Persist the result through the existing `DurableToolExecutor` and `ToolResultFact`; do not add a table or mutate `RunExecutionState` from the handler.

Append the new definition while retaining the current `figura-web-v2` registry version and leaving every existing definition and replay effect unchanged. `AgentRequestBuilder` currently requires historical tool calls to match the active registry version, so changing the version would prevent existing Session history from being assembled. This change is additive to the current call contract and does not need a compatibility registry or a version migration.

**Alternative considered:** Bump the registry version and retain old definitions for historical requests. That introduces a registry compatibility layer and is unnecessary while the existing tools remain unchanged.

## Risks / Trade-offs

- [A whole Attachment may contain multiple charts] → Preserve full-source coordinates and warnings; let the Agent choose an isolated Panel when needed.
- [Baseline detection may be wrong or ambiguous] → Keep geometry separate from calibrated values, use null measurements when the baseline is uncertain, and report confidence and warnings.
- [A dense image may produce a result larger than the existing tool-result limit] → Do not silently truncate candidates; let the existing bounded ToolRuntime reject an oversized result before it is committed.
- [The registry version continues to identify the compatible tool-call contract after an additive tool is added] → Keep every existing tool schema and replay effect unchanged; add a regression check that earlier Session tool messages still assemble under the retained version.

## Migration Plan

No database schema, registry-version, or persisted-record migration is required. New calls use the additive definition in the current registry; existing committed and unresolved tool facts keep their current history and recovery behavior. Rollback consists of reverting the tool registration and code; already committed JSON measurement facts remain valid historical facts and are ignored by a build that does not project this capability.
