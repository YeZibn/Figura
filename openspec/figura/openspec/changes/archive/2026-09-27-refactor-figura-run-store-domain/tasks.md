## 1. Establish the domain boundary

- [x] 1.1 Add `runtime/domain/models.py` and move the existing runtime value classes, enums, aliases, and constants without changing field names, defaults, serialization-facing values, or representations.
- [x] 1.2 Keep `runtime/models.py` and `runtime/__init__.py` as compatibility import surfaces; verify current callers can still import the same names.
- [x] 1.3 Move `_validate_state`, `_validate_provider_attempts`, and `_validate_continuation_state` into pure `runtime/domain/invariants.py`; preserve error codes and ensure domain modules do not import SQLite or persistence modules.

## 2. Extract SQLite infrastructure and mapping

- [x] 2.1 Add `runtime/persistence/database.py` for data-root initialization, database path, connection setup, read/write contexts, and existing transaction/permission behavior.
- [x] 2.2 Add `runtime/persistence/schema.py` for schema version 5, DDL, triggers, indexes, initialization, migrations, and migration integrity checks; preserve every existing schema definition and migration branch.
- [x] 2.3 Add `runtime/persistence/mappers.py` for SQLite row/domain conversion and aggregate row hydration helpers; keep versioned JSON encoding and validation in `runtime/_codec.py`.
- [x] 2.4 Update schema-focused tests to import private schema fixtures from the new schema module, and verify existing databases still open at `user_version = 5` without a rewrite.

## 3. Move persistence operations into repositories

- [x] 3.1 Add `SessionRepository` for Session and attachment metadata operations, preserving attachment validation and file callbacks inside their current write-transaction boundaries.
- [x] 3.2 Add `RunRepository` for idempotency lookup, initial Run creation, scoped state reads, attachment ownership checks, ordered state hydration, and domain invariant validation.
- [x] 3.3 Add `ExecutionRepository` for provider-attempt start/failure, model-response commit, optional continuation and tool-call persistence, and checkpoint updates in the same transactions as today.
- [x] 3.4 Move tool-attempt start/replay and tool-result operations into `ExecutionRepository`; preserve fact order, checkpoint progression, replay semantics, and rollback behavior.
- [x] 3.5 Move completion, failure, and interruption transitions into `ExecutionRepository`; keep terminal status, final record where applicable, checkpoint, and terminal event atomic.

## 4. Restore the stable store façade

- [x] 4.1 Reduce `FiguraRunStore` to repository composition and delegation while preserving its constructor, all current method names/signatures, `data_root`, and `database_path`.
- [x] 4.2 Update internal imports to use canonical domain modules where useful; keep imports through `figura.runtime.models` and `figura.runtime` working for existing consumers.
- [x] 4.3 Confirm `RunCoordinator`, `DurableToolExecutor`, attachment service, Agent request/executor, and Gateway call sites require no behavior or protocol changes.

## 5. Preserve and verify behavior

- [x] 5.1 Retain or extend regression coverage for Session/attachment operations, idempotent Run creation, schema migrations, ordered state hydration, provider attempts/continuations, tool replay/results, and checkpoint recovery.
- [x] 5.2 Verify rollback coverage for initial Run creation, model-response bundles, tool-result transitions, and terminal transitions spanning multiple tables.
- [x] 5.3 Run the focused Figura runtime and attachment tests, then `conda run -n agent python -m pytest -q`; run `git diff --check`.
- [x] 5.4 Compare the initialized schema before and after the refactor: keep `user_version = 5` and the same tables, columns, indexes, triggers, and constraints.
