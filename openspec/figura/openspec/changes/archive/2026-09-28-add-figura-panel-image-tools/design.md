## Context

See `proposal.md` for motivation and user-visible scope. The current Agent request builder resolves every attachment on every model action. Run inputs already preserve ordered attachment IDs, Session Memory projects earlier terminal Run inputs and complete tool facts, and the durable Tool Runtime supports replay-safe reads and idempotent local writes. The Gateway currently composes an empty tool registry. Provider messages already accept image blocks only in user-role messages; image bytes must therefore be projected into a user message, never placed in a tool result.

The proposal changes the Agent image policy and introduces durable Panel assets. It must keep the existing ownership boundaries: Run facts and checkpoints remain Runtime-owned; attachments remain Session-owned; tool results remain bounded JSON; image bytes remain private files; Web responses remain Session-scoped projections.

## Goals / Non-Goals

**Goals:**

- Reconstruct one simple `RunExecutionState` from current Run facts, earlier terminal Run inputs, attachment metadata, and committed Panel records.
- Keep all same-Session attachment references available across Runs while sending bytes only after explicit `load_image` calls.
- Make rectangular and nonrectangular model-proposed regions follow one polygon contract and persist an independent PNG for each Panel.
- Reuse the current durable tool execution and file-reconciliation patterns without adding a compatibility facade or duplicate mutable state.
- Let the existing Figura Web client display committed Panel previews through bounded read-only APIs.

**Non-Goals:**

- Measurement, evidence selection, generated ChartSpec artifacts, review, rendering, publication, or semantic region validation.
- Manual Panel editing, user approval controls, image annotation, or image deletion.
- Persisting image bytes in Run facts, tool-result JSON, browser state, or Provider continuation.
- Adding measurement or review placeholders to `RunExecutionState`.

## Decisions

### 1. Treat RunExecutionState as a projection, not another persisted aggregate

Define a frozen read model with three top-level fields:

| Field | Shape | Source |
|---|---|---|
| `run_id` | opaque Run ID | target `RunState.run` |
| `available_attachments` | ordered entries `{attachment_id, filename}` | distinct attachment IDs from every earlier terminal Run in the Session, then the target Run, resolved through existing attachment metadata |
| `panels` | ordered `PanelRecord` values | committed Panel records in the target Session |

`PanelRecord` contains exactly `panel_id`, `session_id`, `run_id`, `source_attachment_id`, `name`, and `points`. `points` is the immutable normalized polygon supplied at creation. The Panel PNG path is derived from `panel_id` and is not part of the record or projection. Dimensions are read from the validated image when `load_image` resolves it; they are not duplicated in durable metadata.

Build this view for a model action and for an image tool call from the same Session facts and repository reads. Do not store, mutate, or checkpoint the view. Do not add fields for active image, measurement, review, counters, summaries, or prompt state. Existing Session Memory remains the complete ordered conversation projection; RunExecutionState is the image/Panel inventory needed for execution.

### 2. Use one polygon representation for every Panel

`decompose_chart_image` accepts:

```json
{
  "attachment_id": "opaque-attachment-id",
  "panels": [
    {
      "name": "Revenue by region",
      "points": [{"x": 80, "y": 120}, {"x": 920, "y": 120}, {"x": 850, "y": 880}, {"x": 140, "y": 900}]
    }
  ]
}
```

Coordinates are integers normalized to 0–1000 against the original image dimensions. A rectangle is represented by four corner points, so the tool schema does not need separate rectangle and polygon branches. Bounds and point-count checks exist only to make crop execution finite and safe; no overlap, chart-type, visual-accuracy, or semantic check changes the submitted region. Use a maximum of 32 Panels and 64 points per Panel. Rasterize each polygon into a mask, crop to its bounding box, and encode a standalone PNG with transparency outside the mask. Overlapping source regions remain independent Panel files.

### 3. Keep image inventory text separate from image bytes

At each model action, project the complete durable text/tool history, then add one transient user-role text inventory listing every `available_attachments` entry and every committed Panel ID/name/source attachment. This inventory is derived from RunExecutionState and is not persisted as a conversation message.

`load_image` accepts `source_kind` (`attachment` or `panel`) and `source_id`. Its persisted JSON result contains only the source kind, ID, display name, and dimensions. The handler resolves the ID against RunExecutionState before reading the authorized source. The request builder resolves image bytes only for successful `load_image` calls in the immediately preceding committed tool batch, appending one user-role message with IDs/names and image blocks in call order. Duplicate IDs in that batch are included once. A subsequent model response and tool batch do not inherit those bytes; the model calls `load_image` again when it needs visual context.

This policy leaves complete Run messages and attachment references intact while preventing historical original bytes from being attached to each request. An image in an earlier Run remains readable because its ID is included in the current Session inventory. Starting a new Run does not automatically attach bytes loaded in an earlier Run.

### 4. Keep Panel persistence in a focused Panel domain

Add a `src/figura/panels/` package for Panel record/geometry validation, Panel image crop encoding, Panel metadata access, and private image storage. Add a SQLite schema migration and a focused repository for Panel metadata rather than expanding the Run state JSON or `FiguraRunStore` into a generic content blob. The metadata table stores the six PanelRecord fields; the private image filename is derived from `panel_id`.

The image tool handlers live in a focused image-tools module and receive the Panel service, attachment service, and RunExecutionState reader through the Gateway composition root. The reader uses the existing Run coordinator/store APIs to read the current and prior terminal Run facts. Tool handlers do not access SQLite directly and do not bypass the existing durable tool executor.

### 5. Reuse durable tool replay semantics

Register `load_image` as `replay_safe` and `decompose_chart_image` as `idempotent_local_write`. Use the existing call-scoped idempotency key to derive stable Panel IDs by call and Panel position. Stage PNGs first, install them using server-controlled private paths, then commit Panel metadata through the repository's transactional file-install pattern. Replaying the same call returns the same ordered Panel records. Startup reconciliation removes uncommitted orphan files and detects committed records with missing or invalid files; it never silently substitutes a different image.

A Panel becomes visible in RunExecutionState, Gateway list responses, and the frontend only when its corresponding successful `decompose_chart_image` ToolResultFact is committed. This prevents partially completed writes from appearing as completed Panel output. Existing `ToolResultFact` remains bounded JSON and records only Panel IDs and display metadata, not image bytes.

### 6. Directly migrate request construction and registry composition

Replace the existing `_user_content` behavior in `AgentRequestBuilder` with RunExecutionState inventory projection and immediately-preceding-load-image projection. Remove automatic resolution of each historical/current Run input into `ImageBlock`s. Update all callers and tests to the single new behavior; do not retain an old mode, adapter, compatibility facade, or duplicate request path.

Register both image tools in the Figura Gateway registry and increment its tool-registry version. Existing Runs with no tool calls continue to use their durable text history. The current fail-closed behavior for unknown historical tool registry versions remains; no legacy tool registry implementation is added.

### 7. Expose Panel output as read-only Session resources

Add Session-scoped list and content reads following the current attachment route and DTO conventions. Metadata contains `panelId`, `runId`, `sourceAttachmentId`, `name`, and `points`; image content returns `image/png` with `Cache-Control: no-store`. The content route delegates authorization and file validation to the Panel service and never returns a local path.

Add methods only to the Figura client contract/adapter and a small Panel presentation grouped by originating Run. Fetch previews through the client on demand. Do not change ChartAgent/mock APIs, shared legacy clients, or direct component-to-Gateway transport boundaries.

### Alternatives considered

- **Persist RunExecutionState as a JSON blob:** rejected because it duplicates attachment and tool-result facts and can drift after interrupted commits.
- **Keep one active-image field:** rejected because one Run can explicitly load several images and a Session can retain many earlier attachments.
- **Use separate rectangle and polygon geometries:** rejected because a rectangle is already a four-point polygon and a single schema reduces branching.
- **Attach every historical image on every Provider request:** rejected because it repeatedly transfers image bytes and scales request size with Session history.
- **Return image bytes inside ToolExecutionResult:** rejected because tool results are durable, bounded JSON and image bytes belong in private files plus the Provider request projection.
- **Preserve the old request builder behind an adapter or mode flag:** rejected because the current project has one Figura request behavior and the direct migration is easier to reason about.

## Risks / Trade-offs

- **A Session's full image inventory can grow:** the project currently requires complete cross-Run history and no pruning. Provider text limits remain authoritative; an oversized inventory fails before Provider-attempt claim instead of silently omitting IDs.
- **Many explicitly loaded images can exceed Provider limits:** validate the assembled request before claim; the model can load fewer images in a later tool round.
- **Model polygon coordinates can be malformed or visually poor:** enforce only bounded executable geometry, report structural errors, and preserve valid proposals exactly. Visual quality is outside this change.
- **SQLite metadata and files cannot share a native transaction:** stage/rename, deterministic Panel IDs, idempotent replay, and startup reconciliation handle interruption without exposing partial results.
- **Provider image/tool combinations may differ:** retain Provider-neutral contracts and verify the selected Qwen, DeepSeek, and MiMo request mappings with real multimodal tool-call cases during implementation.
- **Registry version changes:** the new registry has one explicit version. No compatibility registry is retained; any older unrecognized tool-history version continues to fail closed under the existing durable execution contract.

## Migration Plan

1. Add the Panel metadata table and private Panel image directory through a versioned SQLite migration. Existing attachment and Run rows need no data rewrite.
2. Add RunExecutionState projection, Panel service/repository, and the two image tools; wire them into the single Figura Gateway composition.
3. Replace automatic image injection in the existing request builder and update all request fixtures/callers to the new inventory plus explicit-load behavior.
4. Add Session-scoped Panel reads and Figura-only frontend presentation.
5. Run focused backend, recovery, Provider adapter, route, and frontend validations. If implementation must be rolled back, stop exposing Panel routes/tools and revert the migration-aware code while leaving new Panel rows/files untouched; do not rewrite existing Run facts.

## Open Questions

None. The image inventory scope, geometry contract, Panel persistence boundary, request projection, and absence of a compatibility layer are decided for this change.
