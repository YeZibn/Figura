## Context

See `proposal.md` for motivation. The current persistence boundary is `FiguraRunStore` in `src/figura/runtime/store.py` (about 2,400 lines). It combines SQLite startup and migrations, transaction management, queries and writes, row conversion, payload encoding, and cross-record Run invariants. Immutable runtime values are defined in `runtime/models.py`; JSON fact codecs are already isolated in `runtime/_codec.py`.

Compatibility constraints:

- Callers construct `FiguraRunStore(data_root)`, read `data_root` and `database_path`, and invoke its existing Session, attachment, Run, provider-attempt, and tool-attempt methods.
- Runtime models are imported from `figura.runtime.models` and `figura.runtime`; keep both import surfaces working.
- The current SQLite `user_version` is 5. Existing databases and all migrations must continue to open without a data rewrite.
- A number of writes intentionally span multiple tables. They must continue to commit or roll back as one SQLite transaction.

## Goals / Non-Goals

**Goals:**

- Give domain values and pure Run-state invariants a location that does not depend on SQLite.
- Separate database/schema work, row mapping, and repository operations from the `FiguraRunStore` entry point.
- Keep storage operations grouped around domain transactions, including attachment file callbacks that currently run inside a database write transaction.
- Preserve the current persisted model fields, serialized formats, database version, errors, ordering, and public Python call surfaces.

**Non-Goals:**

- Add a Session-level history or memory API, combine messages from different Runs, or change what a provider receives as context. Complete cross-Run message memory is a later change.
- Add retention, pruning, truncation, or a memory budget policy.
- Add or remove database tables/columns, bump schema version, or change any persisted JSON/versioned payload.
- Change RunCoordinator, provider selection, tool behavior, Gateway/API contracts, or the frontend.

## Decisions

### 1. Keep `FiguraRunStore` as a composition-based compatibility façade

`runtime/store.py` keeps the `FiguraRunStore` class, constructor, method names and signatures, and `data_root` / `database_path` attributes. Its constructor creates one database owner and the repositories that use it; each façade method delegates to the repository that owns that operation. `RunCoordinator`, `DurableToolExecutor`, the attachment service, and callers do not need to know repository classes.

Composition keeps the public object stable while removing SQL implementation from the public entry point. Inheritance-based repositories were considered, but would keep methods and transaction ownership spread across one implicit object and make it harder to see which component starts a transaction.

### 2. Make the domain package the canonical owner of runtime values and invariants

Add `runtime/domain/` with:

- `models.py`: the existing immutable runtime values and enums, with their current names, fields, defaults, and representations.
- `invariants.py`: the pure Run-state checks currently implemented by `_validate_state`, `_validate_provider_attempts`, and `_validate_continuation_state`. It accepts domain values and raises the existing `RunError` codes; it imports no SQLite modules.

Keep `runtime/models.py` as a compatibility re-export of `runtime/domain/models.py`; keep `runtime/__init__.py` exports unchanged. Update internal imports gradually to use the canonical domain package. Do not redesign or merge the existing records as part of the move.

The model ownership inventory remains:

| Domain value | Fields owned by the value |
| --- | --- |
| `Session` | `session_id`, `name`, `created_at`, `updated_at` |
| `AttachmentMetadata` | `attachment_id`, `session_id`, `filename`, `media_type`, `byte_count`, `created_at` |
| `Run` | `run_id`, `session_id`, `ordinal`, `input_record_id`, `status`, `provider`, `model`, `created_at`, `started_at`, `finished_at`, `terminal_code`, `terminal_message`, `final_record_id` |
| `RunInput` | `text`, `attachment_ids`, `requested_provider`, `requested_model`, `schema_version` |
| `ModelResponseFact` | `provider_id`, `model_id`, `assistant_content`, `finish_reason`, `usage`, `provider_response_id`, `continuation_ref`, `schema_version` |
| `FinalAnswerFact` | `response_record_id`, `artifact_refs`, `guard_version`, `schema_version` |
| `ExecutionRecord` | `record_id`, `run_id`, `record_sequence`, `record_kind`, typed `payload`, `created_at` |
| `ToolCallFact` | `response_record_id`, `call_id`, `tool_name`, `arguments_json`, `position`, `registry_version`, `schema_version` |
| `ToolAttemptStartedFact` | `tool_call_sequence`, `call_id`, `attempt_id`, `attempt_number`, `replay_effect`, `registry_version`, `schema_version` |
| `ToolResultFact` | `tool_call_sequence`, `attempt_id`, `call_id`, `tool_name`, `outcome`, `result`, `error`, `schema_version` |
| `ToolExecutionFact` | `run_id`, `tool_sequence`, `fact_kind`, `schema_version`, typed `payload`, `created_at` |
| `ProviderAttempt` | `attempt_id`, `run_id`, `attempt_sequence`, `base_record_sequence`, `base_tool_sequence`, `status`, `response_record_id`, `failure_code`, `started_at`, `finished_at` |
| `ProviderContinuationFact` | `continuation_id`, `run_id`, `response_record_id`, `provider_id`, `format_version`, `schema_version`, `reasoning_content`, `created_at` |
| `ExecutionCheckpoint` | `run_id`, `revision`, `last_committed_record_sequence`, `last_committed_tool_sequence`, `next_action`, `schema_version`, `updated_at` |
| `NextAction` | `action_kind`, optional `response_record_id`, optional `tool_call_sequence`, optional `attempt_id` |
| `RunStreamEvent` | `run_id`, `event_sequence`, `event_kind`, `payload`, `created_at` |
| `RunState` | the hydrated `run`, ordered `records`, `checkpoint`, ordered `events`, `tool_facts`, `provider_continuations`, and `provider_attempts` |
| `RunCreateRequest` | `session_id`, `text`, `provider_id`, `model_id`, `idempotency_key`, `attachment_ids` |

Move the existing enum values unchanged: `RunStatus` (`running`, `completed`, `failed`, `interrupted`), `RecordKind` (`input`, `model_response`, `final_answer`), `ActionKind` (`model`, `provider_attempt`, `tool_execution`, `tool_attempt`, `final`), `ProviderAttemptStatus` (`started`, `response_committed`, `known_failure`, `outcome_unknown`), `ToolFactKind` (`tool_call`, `tool_attempt_started`, `tool_result`), `EventKind` (`run_created`, `run_completed`, `run_failed`, `run_interrupted`), and `TerminalCode` (`execution_failed`, `invalid_response`, `storage_error`, `interrupted`, `provider_outcome_unknown`). Move `TERMINAL_MESSAGES`, `EventValue` (`str | int | tuple[str, ...]`), `RecordPayload`, and `ToolFactPayload` with the domain types. Keep all current field types, defaults, optionality, and `repr` behavior as-is; `ProviderUsage`, `ReplayEffect`, and tool outcome/error types remain owned by their provider/tool modules. The inventory is a move of current fields, not a request to add fields.

### 3. Split persistence by transaction-owning responsibility

Add `runtime/persistence/` with these boundaries:

| Module | Responsibility |
| --- | --- |
| `database.py` | Own `data_root`, database path, SQLite connection setup, read/write context managers, busy timeout, foreign-key enforcement, and transaction begin/commit/rollback behavior. |
| `schema.py` | Own schema version 5, DDL, triggers/indexes, startup initialization, version migrations, and migration integrity checks. It is the only module that changes schema version. |
| `mappers.py` | Convert SQLite rows and versioned JSON payloads into domain values, and domain values into row values where needed. It does not open connections or start transactions. |
| `session_repository.py` | Own Session and attachment metadata operations: create/assert Session, register/list/read/delete attachments, and attachment-file reconciliation callbacks. |
| `run_repository.py` | Own idempotency lookup, initial Run creation, scoped Run-state reads, and aggregate hydration. |
| `execution_repository.py` | Own provider-attempt, model-response, tool-attempt/result, checkpoint, and terminal Run transitions. Each public transition owns one complete write transaction. |

The existing `runtime/_codec.py` remains the versioned JSON/fact validation boundary. It is not folded into the database mapper because payload version validation is independent from SQLite row layout. `runtime/errors.py` remains the shared error vocabulary. Repository classes are internal; they are not exported from `runtime`.

`RunState` is hydrated by `run_repository.py`: fetch the Run, checkpoint, execution records, stream events, tool facts, provider continuations, and provider attempts in their established sequence order; map rows; then call the pure domain invariant validator. Attachment ownership for input references is checked in the same read/write transaction that loads or creates the Run.

### 4. Preserve table ownership and current field-to-table mapping

The schema and mapping stay unchanged:

| Existing table | Persisted responsibility |
| --- | --- |
| `sessions` | Session identity, optional name, creation and update timestamps |
| `attachments` | Attachment metadata owned by a Session; image bytes remain in the attachment service's ID-derived files |
| `runs` | Run identity, Session ordinal, provider/model, lifecycle status, terminal fields, and input/final record references |
| `run_execution_records` | Ordered immutable input, model-response, and final-answer records; typed payload remains encoded by `_codec.py` |
| `run_idempotency` | Session-scoped idempotency digest, request fingerprint, Run reference, and creation time |
| `run_execution_checkpoints` | Revision, committed record/tool sequence cursors, next action, schema version, and update time |
| `run_stream_events` | Ordered immutable Run lifecycle events and payloads |
| `run_tool_execution_facts` | Ordered immutable tool-call, attempt-start, and result facts |
| `run_provider_continuations` | Private provider continuation tied to its response record |
| `run_provider_attempts` | Ordered provider attempt state and its response/failure linkage |

`RunState` is a read model assembled from these existing records, not a new persisted blob. No separate Session-memory table is introduced by this refactor.

### 5. Keep multi-record transitions together in one repository method and transaction

Repositories may be separated by operation, but not by table writes. Preserve these transaction units:

1. **Initial Run creation:** validate Session and attachment ownership, resolve idempotency, allocate the Session ordinal, then persist the Run, input record, initial checkpoint, idempotency mapping, and `run_created` event atomically.
2. **Model response commit:** persist the response, optional private continuation, ordered tool-call facts, provider-attempt response linkage when present, and updated checkpoint atomically.
3. **Tool execution transitions:** persist attempt-start or tool-result facts with the corresponding checkpoint/next-action update atomically; retain replay-attempt behavior and sequence validation.
4. **Run terminal transition:** persist terminal status, final record where applicable, checkpoint update, and terminal event atomically.
5. **Attachment registration/deletion:** keep file-install/removal/reconciliation callbacks at their current points relative to the SQLite write lock and metadata transaction.

Splitting writes into table-oriented repositories was rejected because it could commit a response without its checkpoint or event. `execution_repository.py` therefore remains the transaction owner for a complete state transition and may use mapper/helper functions, but it does not delegate part of that transition to a second transaction.

### 6. Refactor in place without a database migration

The migration is a Python module-ownership refactor only. Preserve `PRAGMA user_version = 5`, existing migration branches, table and trigger definitions, indexes, constraints, SQLite pragmas, record ordering, and encoded payloads. No startup rewrite, data backfill, or new file layout is needed. Keep `_CORE_SCHEMA` accessible to its existing tests by moving the test import to the canonical schema module; it is not part of the public `FiguraRunStore` API.

## Risks / Trade-offs

- **A transaction is accidentally split across repositories** → Keep each listed aggregate transition in one repository method and one `database.write()` scope; test rollback cases that cover multiple tables.
- **Compatibility imports break while models move** → Retain `runtime.models` and `runtime.__init__` re-exports and verify representative imports used by Agent, coordinator, codecs, and tests.
- **Row conversion subtly changes nullability, ordering, or payload validation** → Move conversions mechanically, keep `_codec.py` authoritative, and cover reopen/hydrate and existing migration cases.
- **A circular dependency forms between domain, persistence, and runtime façade** → Enforce one-way imports: domain imports no persistence; mappers import domain and codec; repositories import database/schema/mappers/domain; façade imports repositories.
- **Attachment file callbacks move outside the database lock** → Keep callback placement unchanged inside the repository transaction and retain attachment failure/recovery coverage.
- **Internal split adds indirection without reducing responsibility** → Keep repositories grouped around Session/attachment operations, Run creation/read, and complete execution transitions; do not create one class per table.

## Migration Plan

1. Add the domain package and move the current data classes/enums without changing field definitions; leave compatibility re-exports in place.
2. Extract pure invariants, schema initialization, database transaction handling, and row mapping while `FiguraRunStore` still forwards through these modules.
3. Move Session/attachment, Run creation/read, and execution transition methods to their respective repositories. Preserve the exact transaction units above.
4. Keep the façade signatures and attributes stable; migrate internal callers only where doing so clarifies canonical ownership. Update private schema imports in tests to the schema module.
5. Run the existing Figura runtime, attachment, provider-attempt, and durable-tool regression coverage, then the full project validation required by the apply workflow. Compare initialized databases to confirm version 5 and unchanged table/trigger/index definitions.

Rollback is a code revert: because this change performs no database migration and writes the same schema and payloads, the previous `FiguraRunStore` can reopen the database.
