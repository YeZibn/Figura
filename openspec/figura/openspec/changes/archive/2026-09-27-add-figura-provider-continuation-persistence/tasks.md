## 1. Internal continuation contracts and codec

- [x] 1.1 Add a private typed continuation fact with Run ID, model-response ID, opaque continuation ID, provider ID, format version, payload schema version, raw continuation content, and creation time; hide private content from `repr`.
- [x] 1.2 Add optional `continuation_ref` to `ModelResponseFact`; encode new model responses as schema version 2 and keep strict decoding for existing version 1 records.
- [x] 1.3 Enforce nonempty valid UTF-8 continuation content and the 512 KiB byte bound without truncation; reject unknown versions and inconsistent reference fields.

## 2. Additive SQLite schema migration

- [x] 2.1 Add the append-only continuation table with a same-Run response foreign key, model-response kind validation, uniqueness per Run/response, provider/version fields, and the payload byte constraint.
- [x] 2.2 Implement fresh-store and transactional schema 1-to-3 / 2-to-3 initialization paths; preserve existing records and validate foreign keys and `quick_check` before committing `user_version=3`.
- [x] 2.3 Add migration coverage for fresh, v1, and v2 stores, including migration failure rollback and preservation of existing Run identities, facts, checkpoints, events, and idempotency mappings.

## 3. Atomic model-response commit

- [x] 3.1 Update `RunCoordinator` to validate response/Run/provider identity and continuation version/content, then create the opaque response and continuation references and construct the version 2 model-response fact.
- [x] 3.2 Update `FiguraRunStore.commit_model_response` to revalidate references and atomically write the model response, optional private continuation, ordered tool-call facts, and checkpoint in the existing transaction.
- [x] 3.3 Add tests for text responses and tool-call responses with and without continuation, plus stale revision, provider mismatch, unsupported version, oversized UTF-8 payload, duplicate reference, and full rollback with no partial state.

## 4. Run reconstruction, recovery, and privacy

- [x] 4.1 Load typed continuation facts into internal `RunState` with private `repr`; validate that every response reference resolves exactly once to the same Run, response, provider, and format version, and reject orphan or dangling facts.
- [x] 4.2 Add close/reopen tests proving the exact continuation is recoverable after restart and retained after replay and terminal Run transition; verify reads do not call a Provider/tool or change checkpoint progress.
- [x] 4.3 Add privacy and integrity tests proving continuation payloads/references are absent from public Run summaries, events, logs, traces, repr, and user-facing errors, and corrupt/missing/unsupported rows fail closed.

## 5. Compatibility and verification

- [x] 5.1 Verify strict version behavior: existing model-response v1 rows remain readable; new v2 rows round-trip; unknown response/continuation versions fail closed; non-response facts remain version 1.
- [x] 5.2 Run focused Figura Provider/Run/durable-tool regression tests, then the full Python suite in the `agent` Conda environment.
- [x] 5.3 Run `openspec validate add-figura-provider-continuation-persistence --strict --no-interactive --store figura` and confirm the change status and all planned scenarios.
