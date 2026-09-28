## Context

See [proposal.md](proposal.md) for the motivation and scope. The current Figura tree already has useful top-level capabilities (`agent`, `memory`, `providers`, `tools`, `chartspec`, `gateway`, and `runtime`), but attachment and Panel code live in separate packages, Panel code also owns an Agent-facing Run projection, Runtime persistence combines several transaction families, and Gateway contains both HTTP behavior and the application composition factory.

The SQLite schema is version 6. Attachment and Panel files are private local files, and execution records, tool/provider attempts, checkpoints, and stream events are durable. Memory is currently a projection from committed Run facts and includes complete earlier Run history. These are behavior and storage constraints for the move.

## Goals / Non-Goals

**Goals:**

- Organize top-level code by Figura capability, with a small shared area only for genuinely cross-cutting code.
- Keep related models and helpers together. Split a file when it mixes independent responsibilities or has become difficult to navigate, not merely because it contains multiple declarations.
- Give attachment and Panel code one `sources` home; put Run-derived image state under Agent; keep concrete tools under Tools.
- Keep database access and transaction ownership in one shared SQLite component while separating persistence work by Session, Run, Provider, Tool, and source data.
- Preserve complete cross-Run Memory projection and every existing API, tool, provider, database, file, and recovery contract.

**Non-Goals:**

- Require each module to use `domain/`, `application/`, and `infrastructure/`, or require a class-per-file layout.
- Redesign models, persistence schema, public routes, event payloads, prompts, or tool behavior.
- Add Memory pruning, budgeting, summary records, or a second persistence mechanism.
- Move `src/chartagent/`, frontend code, or test files.

## Decisions

### 1. Use capability packages and moderate file grouping

Use this as the target outline. Existing Provider and ChartSpec files remain grouped as they are unless implementation discovers a concrete mixed responsibility. The outline lists meaningful modules rather than every class:

```text
src/figura/
  bootstrap.py
  shared/
    json_schema.py
    image_limits.py
  storage/
    database.py
    schema.py
  providers/                 # retain current package layout
  chartspec/                 # retain current package layout
  memory/
    models.py
    projector.py
  agent/
    executor.py
    request.py
    execution_state.py
    assets/system-v1.md
  sources/
    models.py
    attachments.py
    panels.py
    repository.py
    storage.py
    imaging.py
  runtime/
    models.py
    records.py
    errors.py
    validation.py
    record_validation.py
    coordinator.py
    tool_execution.py
    run_lock.py
    store.py
    persistence/
      sessions.py
      runs.py
      run_transitions.py
      providers.py
      tools.py
      snapshots.py
      mappers.py
      codecs/
        records.py
        tools.py
        events.py
  tools/
    contracts.py
    registry.py
    runtime.py
    provider.py
    limits.py
    implementations/image.py
  gateway/
    __main__.py
    application.py
    server.py
    dispatcher.py
    web_projection.py
```

Files may contain related classes and functions. In particular, keep Provider contracts together in `providers/models.py`, ChartSpec values together in `chartspec/models.py`, Memory message values together in `memory/models.py`, and Sources values together in `sources/models.py`. Do not create empty package layers or one-file-per-class modules.

The shared SQLite connection manager and schema initializer move to `storage/` because Sources and Runtime use the same file and transaction boundary. `shared/` remains limited to reusable JSON-schema and image-limit helpers; it is not a general-purpose dumping ground.

### 2. Keep Memory as the complete conversation projection

Retain `memory/models.py` and `memory/projector.py`. Update only their imports when Runtime facts move. The projector continues to assemble all terminal prior Runs in ordinal order; Agent request assembly continues to append the current Run. Do not filter, summarize, truncate, or budget this history, and do not persist a second copy of the projected messages.

### 3. Make Sources own attachments and Panels

Move the existing attachment service, Panel service, models, repository operations, local file handling, and crop/mask code under `sources/`. Related attachment and Panel classes may share `models.py`; repository code may handle both row families if it remains readable. Keep one local storage module while its file responsibilities remain cohesive.

Preserve attachment ownership checks and reference-checked deletion in the same write transaction as their metadata/file operations. Panel creation retains deterministic IDs, idempotent replay, staged PNG installation, and rollback cleanup. Sources uses the shared SQLite manager and does not create a second database.

Sources continues to use the existing safe Run error codes at the current Gateway/Tool boundary; this refactor does not introduce a second error hierarchy.

### 4. Keep Runtime cohesive and split persistence by transaction family

Retain `runtime/` as the owner of Session/Run lifecycle and durable execution. Group core state values in `models.py`; group persisted response, tool, and event facts in `records.py`. Keep focused validation in two modules: Run/checkpoint invariants and attempt/fact validation.

Split the current execution repository by atomic transaction family: Provider attempt/response commits, Tool attempt/result commits, and Run terminal transitions. Keep Run creation/state reads together in `runs.py`; keep Session operations in `sessions.py`. Put cross-table Session snapshots in `snapshots.py` so they use one read transaction. Keep row conversion in one `mappers.py`; split codecs into the three persisted payload families shown in the tree.

Retain the existing `FiguraRunStore` as the Runtime-facing composition/facade used by the coordinator. It delegates to the focused repositories and no longer owns attachment CRUD or file operations. This avoids a broad caller rewrite while removing the actual source of persistence crowding. Do not add another forwarding layer or old-path compatibility modules.

### 5. Put derived Run image state in Agent and concrete handlers in Tools

Move `AvailableAttachment`, `RunExecutionState`, `RunExecutionStateService`, and `latest_loaded_images` from `panels/execution_state.py` into `agent/execution_state.py`. This state is reconstructed from Run inputs, committed tool facts, attachments, and Panels; it is not a new persisted model.

Move image handlers to `tools/implementations/image.py`. Tools must not import Agent or Runtime implementation modules. Inject a small source-availability callback into the image-tool factory from bootstrap; the callback is implemented using Agent execution state. The handler then resolves image bytes and metadata through Sources. Keep this seam local to image-tool construction rather than adding a new layered package.

### 6. Separate composition from HTTP handling

Move `create_application` and dependency construction from `gateway/application.py` to `bootstrap.py`. Keep `gateway/application.py` focused on HTTP application behavior, `server.py` on the HTTP server, `dispatcher.py` on background Run dispatch, and `web_projection.py` on response/event projection. The launcher imports the factory from bootstrap. Preserve route behavior, request/response fields, SSE event identity, and lifecycle cleanup.

### 7. Migrate callers directly and preserve public behavior

Update source and test imports to the new module locations. Remove the old `attachments/` and `panels/` packages after all callers move. Keep `runtime/`, `memory/`, `providers/`, `chartspec/`, `tools/`, and `gateway/` as capability package names. Do not add forwarding imports from removed paths.

No database migration is needed: schema version 6, DDL, serialized payloads, file locations, permissions, and stored data remain unchanged. Preserve atomic Run creation/idempotency, Provider/Tool commit ordering, checkpoint updates, stream events, and startup file recovery.

### Alternatives considered

- **Apply three architecture layers to every capability and place every declaration in its own file:** rejected because it creates navigation overhead without clarifying these small, cohesive modules.
- **Leave the current tree untouched:** rejected because source ownership and Run-derived image state are misplaced, and the execution repository mixes multiple transaction families.
- **Replace `FiguraRunStore` with a larger set of new ports and facades:** rejected for this structural pass; focused SQLite repositories behind the existing Runtime composition point are sufficient.

## Risks / Trade-offs

- **Moving file and row operations can break atomic rollback or recovery** → move service, repository, and storage behavior together; preserve same-transaction checks and existing rollback/reopen tests.
- **Splitting Runtime commits can change event/checkpoint ordering** → split only at existing transaction boundaries and keep each records/checkpoint/event write in one repository method and transaction.
- **Moving image state can introduce an Agent/Tools import cycle** → inject a small availability callback from bootstrap and verify Tools does not import Agent or Runtime internals.
- **Memory history can be accidentally shortened during import changes** → leave projector behavior unchanged and retain tests that cover ordered prior Runs, current Run, tool calls, and observations.
- **Removing old package paths can leave hidden callers** → search source and tests for old imports before deleting packages; update callers directly without compatibility modules.

## Migration Plan

1. Move shared JSON and image-limit helpers plus SQLite connection/schema ownership; add the composition factory in `bootstrap.py` while keeping current behavior.
2. Move attachments and Panels into Sources, including their models, repository operations, file storage, and image processing.
3. Move Agent execution-state projection and image handlers; connect them through the injected availability callback.
4. Group Runtime models and records, split validation and persistence by responsibility, and keep each current transaction intact behind `FiguraRunStore`.
5. Update Memory imports without changing projection behavior; update Gateway, launcher, Agent, Tools, and test imports to the target paths.
6. Remove old attachment and Panel packages after stale-import checks; run the existing Figura regression suite and compare any failures with the pre-change baseline.

Rollback is a source-control revert of the package/import move. No database or file migration is required.

## Open Questions

None. The module names and ownership above follow the agreed moderate-granularity layout; implementation may keep related declarations together where splitting would add no clarity.
