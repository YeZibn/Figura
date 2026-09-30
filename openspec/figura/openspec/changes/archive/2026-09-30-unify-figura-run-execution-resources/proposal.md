## Why

`RunExecutionState` currently exposes six separate collections with different detail and lookup behavior: attachments and Panels are resource inventories, while measurements and renders are result projections, Figures retain only summaries, and independent OCR is available only through Memory tool messages. A single typed resource catalog will let Agent tools, request assembly, prompt context, and image recall use the same complete cross-Run content through stable references.

## What Changes

- Replace the six top-level collections with `RunExecutionState.run_id` and one ordered `resources` collection whose entries have a typed `ref` and typed `content`.
- Define stable reference variants for image resources (Attachment/Panel IDs) and tool resources (Run/call IDs); define complete content variants for Attachments, Panels, OCR, measurements, ChartFigures, and renders.
- Reconstruct every resource from its current authoritative owner: Sources metadata/files, Run inputs, or committed tool facts. Preserve committed result/error content and full accepted `ChartFigure` data in the execution view without adding a second durable store or copying image bytes.
- Give consumers common list-by-kind, get-by-reference, and image-read behavior. Image reads resolve authorized Attachment/Panel images, create transient OCR/measurement annotations, read stored render PNGs, and report that a Figure must be rendered before it has image bytes.
- Route tool validation, request inventory, prompt context, and latest-batch visual feedback through the unified resource view. Keep complete chronological ToolMessages in Memory and avoid emitting a duplicate full result payload in the resource index.
- Use one supplied target Run prefix for all resource types; exclude later Runs and uncommitted results, and enforce same-Session authorization when content or image bytes are read.
- **BREAKING**: Remove `available_attachments`, `panels`, `ocr_results`/OCR special reads, `measurements`, `chart_figures`, and `chart_renders` as separate RunExecutionState interfaces and delete their obsolete projection/consumer paths. Migrate every internal caller directly; add no compatibility aliases or adapters.

## Capabilities

### New Capabilities

- `run-execution-resources`: One typed, authorized, reconstructable resource catalog for the target Run and its same-Session history.

### Modified Capabilities

- `panel-image-observation`: Replace separate image and observation inventories with the common resource contract while preserving source authorization and explicit/latest-batch image rules.
- `agent-react-execution`: Build request inventories, tool lookups, and current-batch visual feedback from unified resources while preserving complete Memory history and Provider bounds.

## Impact

- Agent: `execution_state.py`, new resource model/read modules, `request.py`, and all tool consumers that currently read individual state collections.
- Tools/Gateway: migrate Figure assembly, render lookup, image-source resolution, and public render summaries to typed resource queries; keep existing external HTTP/SSE contracts unless their current owner requires an explicit delta.
- Sources/Charts/Runtime: reuse current metadata, private image storage, `ChartFigure`, and durable Run tool facts; no new database table, Run field, tool result protocol, or image-byte copy.
- Tests: replace collection-specific assumptions with reference lookup and cover reconstruction, authorization, cross-Run prefix, result completeness, image reading, and latest-batch feedback.
- Documentation: old six-field inventory descriptions are superseded by this contract and are to be removed or rewritten when the user later requests the overview sync; this proposal does not edit overview documents.
