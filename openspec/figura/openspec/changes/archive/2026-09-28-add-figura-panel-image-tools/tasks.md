## 1. Panel domain and image persistence

- [x] 1.1 Define the immutable Panel record and normalized polygon value with the fields and coordinate bounds from `panel-image-observation`.
- [x] 1.2 Add a versioned SQLite migration and focused Panel repository for Session-owned metadata and deterministic Panel IDs.
- [x] 1.3 Add private Panel PNG storage with polygon masking, staged installation, file validation, and startup reconciliation.
- [x] 1.4 Add focused tests for rectangle and nonrectangular crops, transparent pixels outside polygons, geometry/resource bounds, Panel ordering, and interrupted file writes.

## 2. RunExecutionState projection and image authorization

- [x] 2.1 Implement the read-only `RunExecutionState` projection with only `run_id`, `available_attachments`, and `panels`.
- [x] 2.2 Build the ordered, deduplicated attachment inventory from earlier terminal Run inputs and the target Run input; resolve display filenames through the owning Session's attachment metadata.
- [x] 2.3 Include only committed Panel records from the same Session and enforce inventory membership for image-tool reads and decomposition sources.
- [x] 2.4 Add tests for multiple current attachments, earlier-Run attachments, duplicate references, committed and uncommitted Panels, missing sources, and cross-Session rejection.

## 3. Image tools and durable execution wiring

- [x] 3.1 Define bounded schemas and result contracts for `load_image` and `decompose_chart_image` using the existing supported JSON Schema dialect.
- [x] 3.2 Implement `load_image` as a read-only tool returning metadata only, with bytes resolved later by Agent request assembly.
- [x] 3.3 Implement `decompose_chart_image` as an idempotent local write that produces one independent PNG and Panel record per ordered polygon.
- [x] 3.4 Return ordered Panel IDs and safe display metadata through bounded ToolResultFact JSON; never place image bytes or paths in tool results.
- [x] 3.5 Register both tools in the single Figura Gateway ToolRegistry, set its new registry version, and wire the Panel, attachment, and RunExecutionState services through the composition root.
- [x] 3.6 Add tests for tool schema validation, multiple image loads per batch, ordered Panel results, idempotent replay, crash recovery, and unchanged fail-closed behavior for unknown registry versions.

## 4. Direct Agent request migration

- [x] 4.1 Replace automatic attachment-byte projection in `AgentRequestBuilder` with a textual inventory derived from `RunExecutionState`.
- [x] 4.2 Resolve and append image blocks only for distinct successful `load_image` results from the immediately preceding committed tool batch, preserving call order and user-role placement.
- [x] 4.3 Remove the old automatic `_user_content` path and update every caller and fixture to the single on-demand behavior; do not add a compatibility adapter or mode flag.
- [x] 4.4 Update Agent guidance so it first reads the image inventory, explicitly loads one or more images, and refers to Panels by opaque ID.
- [x] 4.5 Add tests proving initial requests and historical Runs carry no image bytes, multiple images in the latest load batch are attached once, and previous batches are not resent.
- [x] 4.6 Verify Qwen, DeepSeek, and MiMo request serialization for image-plus-tool interaction using provider adapter tests and bounded mocked responses.

## 5. Session-scoped Panel Web reads

- [x] 5.1 Add Gateway routes for listing committed Panels and reading a Panel PNG through its owning Session.
- [x] 5.2 Add bounded Panel DTOs and verify ownership, uncommitted-result filtering, `image/png`, and `Cache-Control: no-store` behavior.
- [x] 5.3 Add Gateway tests for ordered listing, valid content reads, missing files, and cross-Session denial.

## 6. Figura frontend Panel presentation

- [x] 6.1 Add Panel metadata/content methods and protocol types to the Figura client adapter without changing ChartAgent/mock contracts or the shared legacy client facade.
- [x] 6.2 Display committed Panel previews grouped under their originating Run and fetch visible image content on demand.
- [x] 6.3 Add frontend checks for empty Panel state, multiple Panels, failed image fetch, and unchanged ChartAgent/mock behavior.

## 7. Integration and documentation

- [x] 7.1 Run the focused Figura backend/provider/Gateway tests and the required frontend build/smoke checks; resolve regressions without weakening the behavior contracts.
- [x] 7.2 Update the Figura implementation overview and component documents to reflect the implemented Panel owner, RunExecutionState projection, image request flow, and Gateway/Client boundary.
- [x] 7.3 Run OpenSpec validation and review the final diff for accidental edits outside this change and for any leftover compatibility branch or duplicate image state.
