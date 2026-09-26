## 1. Figura Store and Domain Contracts

- [x] 1.1 Add Figura-owned Session, Run, RunInput, ExecutionRecord, ExecutionCheckpoint, RunStreamEvent, and bounded error types with explicit schema versions.
- [x] 1.2 Add initial Figura SQLite schema under an injected data root, with foreign keys, WAL, migration version, and uniqueness constraints for Session ordinals, record/event sequences, and idempotency keys.
- [x] 1.3 Implement Session creation and Session-scoped Run/state reads; reject ownership mismatches before returning records or events.

## 2. Run Creation and Idempotency

- [x] 2.1 Validate bounded nonempty text, empty attachment references, explicit provider/model selection, Session identity, and bounded idempotency keys using the existing Provider configuration contract.
- [x] 2.2 Implement canonical request fingerprints and Session-scoped idempotency key digests; return the original Run for an exact repeat and reject key reuse with changed input.
- [x] 2.3 Commit Run, immutable sequence-1 input record, initial model checkpoint, idempotency mapping, and safe `run_created` event in one transaction.
- [x] 2.4 Cover invalid input/provider configuration and transaction rollback so a rejected creation leaves no partial Run facts.

## 3. Execution Commit and Lifecycle

- [x] 3.1 Implement bounded versioned codecs for `input`, text-only `model_response`, and `final_answer`; reject unknown kinds/versions, nonempty tool calls, and private continuation.
- [x] 3.2 Implement checkpoint revision and sequence compare-and-swap so one model-response commit advances record, checkpoint, and next action atomically.
- [x] 3.3 Implement completion through a validated final-answer reference and one transaction for final record, completed Run, cleared checkpoint action, and terminal event.
- [x] 3.4 Implement failed/interrupted terminal commits with bounded safe reasons and preserved checkpoint action; reject later mutation of any terminal Run.
- [x] 3.5 Cover stale concurrent commits, cross-Run references, unsupported payloads, and terminal-state races with SQLite-backed checks.

## 4. Events and Restart Reads

- [x] 4.1 Construct only allowlisted `run_created`, `run_completed`, `run_failed`, and `run_interrupted` event payloads with a Run-local event sequence independent of record sequence.
- [x] 4.2 Reopen the Figura database and reconstruct Session-scoped Run, ordered committed records, checkpoint, and events without invoking Provider or tools.
- [x] 4.3 Fail closed on missing references, sequence gaps, unsupported schema versions, or cursor mismatch; verify failed transactions expose no event.
- [x] 4.4 Verify events and public projections contain no input text, credentials, raw endpoints, model content, private continuation, or local paths.

## 5. Handoff

- [x] 5.1 Document the internal application API and the deferred Provider/Run, attachment, Agent, Gateway, retry/resume, and private continuation boundaries.
- [x] 5.2 Reconcile `docs/figura-implementation-content.md` with the implemented fields and actual verification results after coding.
- [x] 5.3 Run focused Figura Run tests and strict Figura OpenSpec validation, then inspect `git diff --check` before completion.
