## Context

See `proposal.md` for motivation and `specs/run-execution-core/spec.md` for observable behavior. Figura currently has `src/figura/providers/` only. Its `ProviderFactory` resolves an explicit provider/model from process configuration, while `ProviderContinuation` is transient. The broader architecture document is a draft; this design commits only the Run foundation needed for the next integration step.

## Goals / Non-Goals

**Goals:**

- Make Session ownership, Run identity, immutable input, ordered facts, checkpoint, idempotency, and lifecycle events durable in Figura's own store.
- Offer one internal application boundary for Run creation, text-only response commit, terminal transitions, and restart-safe reads.
- Keep the first record and every later record/checkpoint/event transition atomic and reject unsupported payloads before committing.

**Non-Goals:**

- Calling `ProviderClient.complete`, starting a background worker, or promising a user-visible answer from Run creation.
- Uploading or resolving attachments; executing tools; assembling prompts; making retry/resume child Runs; delivering HTTP/SSE events.
- Persisting `ProviderContinuation` or accepting a provider response whose private continuation cannot yet be retained faithfully.

## Decisions

### 1. One Figura SQLite store with explicit initialization

The store takes an injected Figura data root, creates a dedicated `figura.sqlite3`, and applies a versioned initial schema. It never opens ChartAgent's SQLite database or `.chartagent/` files. Connections enable foreign keys, WAL, and a bounded busy timeout. Every write operation owns one `BEGIN IMMEDIATE` transaction, so ordinal and sequence allocation is serialized with the rows it creates. The later runtime composition layer can decide the user-facing `FIGURA_DATA_DIR` default; this change does not invent one.

Tables for this change are `sessions`, `runs`, `run_idempotency`, `run_execution_records`, `run_execution_checkpoints`, and `run_stream_events`. Foreign keys and unique constraints cover `(session_id, ordinal)`, `(run_id, record_sequence)`, `(run_id, event_sequence)`, and `(session_id, idempotency_key_digest)`. A Session-scoped application method checks ownership before returning a Run, records, checkpoint, or events.

An in-memory store was considered but cannot prove restart reads or transaction rollback. Reusing ChartAgent persistence was rejected because Figura has a separate data boundary.

### 2. Minimal authoritative objects and field ownership

| Object | Fields owned in this change | Write rule |
|---|---|---|
| `Session` | `session_id`, nullable `name`, `created_at`, `updated_at` | Created once; only Session metadata can change its name and update time. |
| `Run` | `run_id`, `session_id`, positive `ordinal`, `input_record_id`, `status`, `provider`, `model`, `created_at`, `started_at`, nullable `finished_at`, `terminal_code`, `terminal_message`, `final_record_id` | Created as `running`; selected provider/model and identity never change; only the coordinator writes terminal fields. |
| `RunInput` in `record_kind=input` | `text`, `attachment_ids=[]`, `requested_provider`, `requested_model`, `schema_version=1` | First record, sequence 1; immutable. Text is nonempty in this change. |
| `ExecutionRecord` | `record_id`, `run_id`, positive `record_sequence`, `record_kind`, versioned `payload`, `created_at` | Append only. Initial supported kinds are `input`, `model_response`, and `final_answer`. |
| `ExecutionCheckpoint` | `run_id`, `revision`, `last_committed_record_sequence`, `next_action`, `schema_version=1`, `updated_at` | One row per Run; revision increments with every committed advance or terminal transition. |
| `RunStreamEvent` | `run_id`, positive `event_sequence`, `event_kind`, bounded `payload`, `created_at` | Insert only; lifecycle event numbering is independent from record numbering. |
| `RunIdempotency` | `session_id`, `idempotency_key_digest`, `request_fingerprint`, `run_id`, `created_at` | Insert in the Run creation transaction; neither raw key nor raw request body is stored in the mapping. |

All IDs are opaque generated strings and all stored times are UTC. The first release stores root Runs only; parent lineage, policy/version snapshots, execution limits, and `work_key` are added when their owning features exist. `Run.provider/model` are the actual fixed choice, while `RunInput.requested_provider/model` preserve what the caller supplied. No secret, raw endpoint, or ProviderProfile is copied into Run.

The architecture draft derives a checkpoint ID from content. For this slice, a persisted integer `revision` is a simpler compare-and-swap token. A future opaque resume checkpoint ID can be derived from Run ID and revision without making it a second authority. A full mutable recovery snapshot was rejected because records already hold the facts.

### 3. Text-only Run creation and Session-scoped idempotency

The internal create request requires a known `session_id`, nonempty bounded UTF-8 text, explicit `provider_id` and `model_id`, empty `attachment_ids`, and a bounded opaque idempotency key. The input boundary rejects unsupported or unavailable selection using the existing provider allowlist/configuration path, without a network request or a fallback provider. The application supplies a `ProviderFactory` or equivalent configuration-only resolver; it does not duplicate the three model IDs.

The coordinator writes the Run, sequence-1 input record, checkpoint `(revision=1, last_committed_record_sequence=1, next_action=model)`, idempotency row, and `run_created` event `(event_sequence=1)` in one transaction. `created_at` and `started_at` are the same accepted time because the Run is considered started once this internal creation call succeeds. No background executor is launched in this change; the running checkpoint is read by a later executor.

The idempotency key digest is SHA-256 of the bounded key. The request fingerprint is SHA-256 of canonicalized Session ID, text, attachment list, and requested provider/model. The same key and fingerprint return the original Run; a changed fingerprint produces a conflict. Idempotency rows remain for the lifetime of their Run in this slice. A time-based expiry was considered but could create a second Run for an earlier accepted request before a retention policy exists.

### 4. Typed fact commits, checkpoint cursor, and supported actions

The internal commit port takes the Session/Run identity, expected checkpoint revision, and a typed payload. It compares the revision and Run status inside the write transaction, appends the next record sequence, and updates `last_committed_record_sequence`, `next_action`, revision, and timestamp together. SQLite uniqueness is a second guard against concurrent writers. Failed validation or a stale revision rolls back the entire transaction.

This change provides three payload codecs:

- `input`: the immutable first record described above; no later append is allowed.
- `model_response`: bounded assistant text, a normalized finish reason, optional bounded usage counters and response ID, empty tool calls, and no continuation. It must match the Run's provider/model and the current `next_action=model`. Commit advances to `next_action=final` with a reference to this response record.
- `final_answer`: a reference to that committed text-only `model_response`, empty artifact refs, and a fixed `text-only-v1` guard version. The response must have a finish reason that permits a final answer. Content is read through the referenced response rather than copied into this record.

The code SHALL reject unknown record kinds or schema versions, unbounded payloads, nonempty tool calls, and any nonempty `ProviderContinuation`. Omitting private continuation from a persisted model response would make future replay incorrect, so rejection is required until a managed private payload store and reference validation exist. A generic arbitrary-JSON execution payload was considered but would make later reader and privacy contracts unverifiable.

This slice supports `next_action=model`, `next_action=final(response_record_id)`, and null after completion. Failed or interrupted Runs preserve the current action for later recovery assessment. Tool/verify/promote actions are defined in later changes with their own typed facts and permission checks.

### 5. One lifecycle writer and transactionally safe events

`RunCoordinator` is the sole application writer for Run status. Completion is valid only while running at `next_action=final`, with a committed response belonging to the same Run. It appends `final_answer`, sets `Run.status=completed`, `Run.final_record_id`, `finished_at`, clears `next_action`, increments checkpoint revision, and writes `run_completed` in one transaction. Failure and interruption set one terminal state and bounded code/message, retain `next_action`, increment revision, and write one terminal event. Any later transition on that Run is rejected. Retry/resume will create child Runs in a later change.

The first event kinds are `run_created`, `run_completed`, `run_failed`, and `run_interrupted`. Payloads are constructed from allowlisted safe fields: creation has Session ID and ordinal, completion has an empty artifact-ref list, and failure/interruption have only a safe terminal code. The event identity is `run_id:event_sequence`; `record_sequence` is never used as an event cursor. A direct serialization of ExecutionRecord was rejected because input text and future private payloads must never enter the public timeline.

### 6. Restart reads do not execute work

The read path reconstructs the Run, ordered records up to the committed checkpoint, checkpoint, and ordered events. It checks schema versions, Session ownership, record sequence continuity, `Run.input_record_id`, terminal final-record reference, and checkpoint cursor consistency. Inconsistent or unknown-version state returns a bounded integrity/version failure. It never calls Provider, executes a tool, or interprets an uncommitted action as completed. This is a recovery read primitive; actual resume and retry policy remain separate.

## Risks / Trade-offs

- **A `running` Run can remain after a process stop because no executor is connected yet** → Keep creation internal in this change and expose committed checkpoint reads; later execution integration decides whether to resume explicitly or create a new child Run.
- **Private thinking data cannot be stored yet** → Reject nonempty continuation during model-response commit; the next Provider/Run integration change must add managed private storage before enabling those responses.
- **SQLite contention can produce stale writers** → Use short write transactions, compare checkpoint revision, unique sequence constraints, and a bounded busy timeout; surface a bounded retryable conflict to the application caller without reissuing provider work.
- **Schema additions will follow as tools and attachments arrive** → Version payloads and migrations, keep one owner per field, and fail closed on unknown versions. Do not create empty placeholder facts for future tools.

## Migration Plan

This is Figura's initial Run schema, so there is no existing Figura Run data to migrate. Database initialization is additive inside the injected Figura root and leaves ChartAgent files untouched. Later schema changes must use explicit migrations and preserve readable committed records; removing this new code must not silently delete a user's Figura database.

## Open Questions

The default user-facing value of `FIGURA_DATA_DIR`, retention/cleanup periods, and the format of future opaque resume checkpoint IDs can be chosen with the Runtime composition and resume changes. None changes this slice's internal store or committed fact semantics.
