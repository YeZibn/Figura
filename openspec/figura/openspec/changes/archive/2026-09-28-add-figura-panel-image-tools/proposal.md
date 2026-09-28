## Why

Figura currently sends every Run's referenced image bytes in each Provider request, so historical attachments are repeatedly transmitted and a composite chart cannot be isolated into independently readable regions. This change adds explicit image observation and Panel creation while preserving all same-Session image references and durable Run history.

## What Changes

- Add `RunExecutionState` as a read-only projection containing the current Run ID, all same-Session attachments referenced by earlier terminal Runs and the current Run, and all committed Panels available in the Session.
- Add `load_image` for on-demand reading of an authorized attachment or Panel by opaque ID. A tool batch may load multiple images for the next model request.
- Add `decompose_chart_image` to turn model-proposed polygon regions into separate, persisted Panel PNG images and records. Every Panel receives its own opaque `panel_id` and image; pixels outside the polygon are transparent.
- Change Agent request assembly to provide the complete image inventory as text and attach only images explicitly loaded by the immediately preceding tool batch. Historical Run images remain available by ID and are not automatically resent.
- Persist Panel metadata and image files with Session ownership, source attachment, originating Run, display name, and normalized polygon geometry; make local writes idempotent and recoverable.
- Add read-only Session-scoped Web access to Panel metadata and image content, and a minimal frontend presentation for created Panels.
- Directly migrate the current request and tool composition paths. Do not add a compatibility facade, legacy image-injection mode, or parallel state store.
- Keep measurement, chart generation, verification, and publication outside this change. Do not add measurement or review fields to `RunExecutionState` yet.

## Capabilities

### New Capabilities
- `panel-image-observation`: Session-scoped image inventory, on-demand image loading, Panel decomposition and persistence, and the reconstructable `RunExecutionState` projection.

### Modified Capabilities
- `agent-react-execution`: Replace automatic historical image-byte injection with complete image references plus explicit, on-demand image loading.
- `figura-web-gateway`: Expose read-only Panel metadata and image content through the owning Session boundary.
- `figura-web-client`: Present Panels created during a Run without introducing manual region editing or review controls.

## Impact

- Python: `src/figura/agent/`, `src/figura/attachments/` or a focused image/Panel domain package, `src/figura/tools/`, `src/figura/runtime/`, and `src/figura/gateway/`.
- Persistence: SQLite Panel metadata plus private managed PNG files under Figura's data root; schema migration and interrupted-write reconciliation are required.
- Provider requests: image blocks remain user-role content. The Agent must project inventory text and the image bytes loaded by the immediately preceding tool batch before claiming a Provider attempt.
- Web: Session-scoped Panel read routes and a bounded frontend preview/list. Existing attachment APIs and Run input protocol remain the source of original attachment IDs.
- Tests: focused coverage for image inventory, image projection, geometry execution, file persistence/recovery, Session isolation, routes, and frontend build behavior.
