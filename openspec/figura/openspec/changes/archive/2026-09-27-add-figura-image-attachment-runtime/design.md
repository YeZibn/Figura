## Context

See `proposal.md` for motivation and scope. Figura already stores Run input as an immutable `RunInput` with an `attachment_ids` field, but creation currently forces it empty. Provider requests already accept in-memory `ImageBlock`s and validate JPEG, PNG, GIF, and WebP with limits of 16 images, `24 MiB - 64 bytes` per image, and 32 MiB total image bytes. The Agent builds and validates a request before it claims a durable provider attempt.

## Goals / Non-Goals

**Goals:**
- Add a private, durable backend lifecycle for Session-owned image files.
- Make attachment ownership and retained bytes checkable inside the same SQLite transaction that creates a Run.
- Preserve the current `RunInput` schema and use its existing ordered `attachment_ids` field.
- Rebuild every model request from the persisted text and images while keeping bytes out of durable facts, events, and logs.
- Keep attachment deletion from invalidating a committed Run.

**Non-Goals:**
- HTTP routes, Gateway behavior, frontend upload/preview/selection, or changes to the old `chartagent` store.
- Image transformations, OCR, image dimensions in metadata, or a content-hash/deduplication system.
- Changing provider/model selection, provider limits, or the provider wire format.

## Decisions

### 1. Persist attachment metadata in Figura's existing SQLite database and bytes as private files

Add one `attachments` table to the database owned by `FiguraRunStore`. Store binary data under `<data_root>/attachments/<attachment_id>.bin`; derive the path from the generated ID, and do not persist a separate storage-path field. Create the directory with owner-only access and files with owner read/write access. The attachment service coordinates the files while `FiguraRunStore` remains the sole owner of SQLite connections and transactions.

The table has exactly these fields:

| Field | Type / bound | Owner and meaning |
| --- | --- | --- |
| `attachment_id` | text primary key, generated UUID hex, 32 characters | Attachment store; opaque reference used by `RunInput` |
| `session_id` | text, foreign key to `sessions.session_id` | Attachment store; the only Session allowed to list, read, resolve, or delete this attachment |
| `filename` | text, sanitized basename, at most 255 UTF-8 bytes | Attachment store; display metadata only, never used as a path |
| `media_type` | text enum: `image/jpeg`, `image/png`, `image/gif`, `image/webp` | Attachment validator; derived from decoded content, not caller input |
| `byte_count` | positive integer, at most `24 MiB - 64 bytes` | Attachment store; actual validated file length |
| `created_at` | UTC timestamp text | Attachment store; creation time for stable listing |

There is no stored `storage_key`, local path, upload URL, image dimension, state flag, or hash. The first change has no public endpoint; internal upload/list/read/delete operations return only the metadata fields above. Image bytes are returned only by an internal Session-scoped resolver for Agent request assembly.

### 2. Validate image bytes before registering an attachment

The upload flow streams at most `MAX_IMAGE_BYTES` into an OS-managed anonymous temporary file inside the private attachment directory, rejects empty content, then uses the already-declared Pillow dependency to verify and decode the image. Map the decoded Pillow format to the Provider boundary's four supported media types. Ignore any client media-type claim, reduce the supplied filename to a bounded sanitized basename, and reject invalid, unsupported, truncated, or oversized data. The temporary file is not discoverable by startup cleanup and is automatically released if the process exits before registration.

Generate the attachment ID on the server. While holding a SQLite write transaction, copy the validated temporary file to an exclusive ID-derived final path and insert its metadata through `FiguraRunStore`. If metadata insertion fails, remove the final file. On attachment-store startup, reconcile trash and final files against metadata while holding the same SQLite write lock: restore a delete tombstone when its database deletion did not commit and remove files with no metadata row. A process interruption can leave only private, non-resolvable final or trash files until this reconciliation runs.

The service accepts up to the Provider's existing per-image byte limit. Run creation limits the selected list to 16 unique IDs; Agent request validation applies both the 16-image and 32 MiB aggregate image limits, as well as the per-image and other request limits. No upload-time aggregate Session quota is added in this change because there is no public upload transport yet; the later Gateway integration must add an explicit storage quota before exposing uploads.

### 3. Keep attachment ownership checks and Run creation in one database transaction

`RunInput` already contains `text`, ordered `attachment_ids`, `requested_provider`, and `requested_model`. Keep its `schema_version` at 1: the codec already reads the ID list, so this change enables its existing field rather than changing the record shape. Do not add a second attachment-reference field to `Run` or an index table.

Before encoding the input fact, `FiguraRunStore.create_initial_run` validates every distinct ID against the `attachments` table and requires the owning `session_id` to match the new Run's Session. The attachment rows and Run records share the same database and transaction, so a concurrent delete cannot remove an attachment between authorization and the immutable input commit. Persist the IDs in caller order in the input record. Keep the existing atomic Run, input record, checkpoint, idempotency mapping, and creation event boundary; no provider request occurs during Run creation.

The creation fingerprint includes the ordered attachment IDs alongside Session, text, and provider/model. Repeating the same key and exact ordered request returns the existing Run; changing an ID or its order conflicts. An attachment ID identifies immutable bytes and metadata for its lifetime.

### 4. Delete only attachments that no immutable Run input references

`FiguraRunStore` checks immutable input payloads in `run_execution_records` while holding its write transaction. It may remove an attachment row only when no input payload for that ID exists. This uses the existing `RunInput.attachment_ids` as the single source of truth and avoids a redundant reference table.

For file/database coordination, move a deletable file into a private trash directory while holding the same SQLite write transaction, delete the metadata row, then commit and unlink the tombstone. If the transaction rolls back, restore the file. Startup reconciliation uses the row's presence to decide whether a tombstone is restored or removed. Reconciliation holds the database write lock so it cannot mistake a file being registered by another process for an orphan. If a Run references the attachment, deletion fails and the file remains at its final ID-derived path. Referenced attachments are retained indefinitely in this change; Run/session retention and cascading cleanup are a later lifecycle decision.

### 5. Resolve images before a provider attempt is claimed

Inject a Session-scoped attachment resolver into the Agent request assembly path. For every model action, use the Run's `session_id` and persisted ordered IDs to load bytes and verified media types, then construct the original user message as the existing text followed by `ImageBlock`s in ID order. Include that same original user message on later model requests after tool rounds, alongside the already committed assistant/tool history.

The request builder runs the existing Provider validation on the assembled request. It resolves all files and checks count, per-image, aggregate image bytes, text, tools, and message bounds before `_execute_model_action` calls `begin_provider_attempt`. Missing, unreadable, invalid, or over-limit files therefore fail the Run without a provider attempt and without network dispatch. Keep the image bytes in memory only for the outbound Provider call; existing `repr=False` on `ImageBlock.image_bytes` and provider adapter logging rules remain in force.

### 6. Bump the SQLite schema, not the RunInput payload schema

Increase the SQLite schema version from 4 to 5 and create the `attachments` table and its Session/time listing index. The migration is additive: existing Sessions, Runs, RunInput records with empty ID lists, checkpoints, events, provider attempts, continuations, and tool facts remain unchanged. No old record needs rewriting.

Before first opening an existing local database with schema v5, keep a backup copy. A rollback to a v4 binary requires restoring that pre-migration database backup; the v5 table is additive but an older binary is not guaranteed to understand the newer schema version.

### Alternatives considered

- **Store image bytes as SQLite blobs:** rejected because it expands the Run database and makes binary I/O share the transaction path for every execution fact.
- **Persist absolute paths or caller filenames as storage keys:** rejected because paths must stay private and caller-controlled names cannot safely determine file locations.
- **Add a normalized Run-to-attachment reference table:** rejected because immutable `RunInput.attachment_ids` already owns the references; a second index would require additional consistency rules.
- **Delete attachments regardless of Run references:** rejected because a later model action or retry would lose part of the immutable input.
- **Add upload HTTP routes and frontend controls now:** rejected for this change so the backend contract and durable Run behavior can be implemented and validated before transport/UI integration.

## Risks / Trade-offs

- **[Risk] SQLite and filesystem changes cannot share one atomic transaction.** → Use anonymous upload staging, perform final placement and metadata changes while holding the database write lock, use tombstones for deletion, compensate failed operations, and reconcile final/trash files against metadata at startup.
- **[Risk] Referenced images remain stored as long as immutable Run inputs remain.** → Reject deletion for referenced files and defer reclamation to a later explicit Run/session retention change.
- **[Risk] There is no aggregate Session storage quota before Gateway integration.** → Keep this capability internal and require the later upload endpoint to enforce a quota before exposing it to users.
- **[Risk] Looking up references during deletion scans immutable input JSON.** → Accept this bounded local-store approach for the initial feature; add a normalized/indexed reference representation only if measured scale justifies its consistency cost.

## Migration Plan

1. Back up the local Figura SQLite database before applying the v4-to-v5 migration.
2. Apply the additive `attachments` table migration and validate SQLite integrity; existing Run facts remain unchanged.
3. Create the private attachment and trash directories on demand with owner-only permissions; use anonymous temporary files for upload staging.
4. If startup or an upload/delete operation fails, stop the affected operation, leave existing Run facts intact, and run file reconciliation on the next store open. Roll back the binary version by restoring the pre-migration database backup.
