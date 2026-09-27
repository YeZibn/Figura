## 1. Attachment metadata and storage migration

- [x] 1.1 Add the schema-version-5 `attachments` table with exactly the six fields and constraints defined in `design.md`, plus a Session/time listing index.
- [x] 1.2 Implement the additive v4-to-v5 migration and verify existing Sessions, Runs, empty attachment lists, checkpoints, events, continuations, provider attempts, and tool facts remain readable.
- [x] 1.3 Extend Run input encoding and validation to persist up to 16 distinct ordered attachment IDs while preserving schema version 1 and backward compatibility with existing empty lists.

## 2. Private image attachment lifecycle

- [x] 2.1 Implement bounded streaming upload to a private staging file, Pillow validation, verified media-type mapping, sanitized filename handling, and server-generated opaque IDs.
- [x] 2.2 Implement Session-scoped metadata listing and image resolution; keep the derived file path and image bytes out of returned metadata and ordinary diagnostics.
- [x] 2.3 Implement private file permissions, anonymous upload staging, atomic final placement with metadata registration, deletion tombstones, and startup reconciliation for final/trash files.
- [x] 2.4 Implement deletion only for unreferenced attachments, checking immutable Run input records in the same SQLite write transaction used to remove metadata.
- [x] 2.5 Add storage regression coverage for supported/invalid/oversized images, MIME spoofing, Session isolation, metadata bounds, interrupted upload/deletion recovery, and referenced-attachment deletion rejection.

## 3. Run input authorization and idempotency

- [x] 3.1 Accept optional attachment IDs in Run creation, reject malformed, duplicate, over-count, missing, unavailable, or cross-Session references, and retain the caller's order in `RunInput`.
- [x] 3.2 Validate attachment ownership within the atomic Run creation transaction so attachment deletion cannot race authorization and immutable input persistence.
- [x] 3.3 Include ordered attachment IDs in the normalized request fingerprint and preserve same-request reuse versus changed-order/reference idempotency conflict behavior.
- [x] 3.4 Add regression coverage for text-only compatibility, authorized image Run creation, rejection without partial Run facts/events, and attachment-aware idempotency.

## 4. Agent image request assembly

- [x] 4.1 Inject the Session-scoped attachment resolver into Agent request assembly and build the original user message from persisted text followed by images in persisted order.
- [x] 4.2 Preserve the same original image-bearing user message when reconstructing later Provider requests after completed tool rounds.
- [x] 4.3 Validate resolved image count, per-image bytes, aggregate image bytes, and the complete Provider request before claiming a durable provider attempt.
- [x] 4.4 Add regression coverage proving missing, unreadable, malformed, and over-limit images fail without a provider attempt or network dispatch, and valid images reach the Provider only in memory.

## 5. Integration and compatibility verification

- [x] 5.1 Run focused attachment, Run-store migration, Run-coordinator, and Agent request/execution tests; fix regressions while preserving existing text-only behavior.
- [x] 5.2 Run the Figura test suite and strict OpenSpec change validation, then inspect the final diff for leaked file paths, bytes, or unplanned fields.
