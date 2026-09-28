## 1. Shared Utilities and Application Composition

- [x] 1.1 Move genuinely shared JSON-schema and image-limit helpers into `shared/`; update current callers without changing validation rules.
- [x] 1.2 Move SQLite connection, transaction, and schema ownership into `storage/`; keep one database file, schema version 6, and existing transaction behavior.
- [x] 1.3 Move `create_application` and component construction into `bootstrap.py`; keep the Gateway launcher and HTTP behavior intact.

## 2. Sources: Attachments and Panels

- [x] 2.1 Move attachment and Panel models, services, and repository operations under `sources/`, grouped by responsibility rather than by class.
- [x] 2.2 Move local file handling and image crop/mask operations under `sources/`; preserve attachment recovery, Panel replay, and atomic file/row behavior.
- [x] 2.3 Update Agent, Tools, Gateway, and tests to use Sources directly; retain the existing access and error behavior.

## 3. Runtime Persistence and Execution

- [x] 3.1 Group core Session/Run state and persisted execution facts into a small number of Runtime modules; keep related declarations together.
- [x] 3.2 Split Runtime persistence by Session, Run, Provider, Tool, and Run-transition transaction responsibilities; retain the existing `FiguraRunStore` composition point.
- [x] 3.3 Group row mapping and persisted codecs by representation; preserve payload versions and every records/checkpoint/event transaction.
- [x] 3.4 Update Runtime and Memory imports while preserving Run creation, idempotency, recovery, and complete cross-Run history.

## 4. Agent State and Concrete Tools

- [x] 4.1 Move Run-derived attachment/Panel availability and latest-loaded-image projection into `agent/execution_state.py`; do not persist this derived state.
- [x] 4.2 Move image handlers into `tools/implementations/image.py` and inject source availability from bootstrap without importing Agent or Runtime internals from Tools.
- [x] 4.3 Keep Memory in `memory/models.py` and `memory/projector.py`; preserve all terminal prior Runs, current-Run messages, tool calls, and observations without pruning or budgeting.

## 5. Direct Import Migration and Removal

- [x] 5.1 Update all Figura callers and focused test imports to the target module paths while preserving test locations and assertions.
- [x] 5.2 Remove the old `attachments/` and `panels/` packages after confirming no callers depend on them; do not add forwarding compatibility modules.

## 6. Regression and Structure Checks

- [x] 6.1 Run focused attachment, Panel, Runtime, Agent, Memory, Tool, and Gateway regressions for preserved behavior and transaction boundaries.
- [x] 6.2 Run the full Figura regression suite, compare failures with the established baseline, search for stale imports, validate OpenSpec, and run `git diff --check`.
