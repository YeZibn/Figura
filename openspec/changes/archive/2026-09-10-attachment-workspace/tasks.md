## 1. Attachment protocol and temporary storage

- [x] 1.1 Define bounded attachment metadata, upload response, attachment state, and attachment-aware message protocol types without exposing local paths or image bytes.
- [x] 1.2 Implement the Gateway-managed temporary attachment store with generated internal paths, per-file and aggregate limits, startup cleanup, and failed-upload cleanup.
- [x] 1.3 Add session-scoped attachment metadata queries and safe registration helpers backed by the existing `AttachmentRegistry` and SQLite references.
- [x] 1.4 Add unit tests for media-type and size validation, content hashing, session ownership, cleanup, metadata projection, and absence of raw bytes or paths in JSON responses.

## 2. Gateway attachment operations

- [x] 2.1 Add bounded binary upload and safe metadata-list routes for an existing session, including filename validation, content-length checks, and loopback/CORS behavior.
- [x] 2.2 Extend text message requests with optional authorized `attachmentIds`, reject unknown or cross-session IDs before Agent execution, and build the existing registered-attachment metadata turn.
- [x] 2.3 Preserve on-demand `load_image` semantics so registration never loads image bytes and only an Agent tool call can create model-visible image content.
- [x] 2.4 Add Gateway API tests for upload, list, invalid content, unknown sessions, cross-session access, attachment-aware messages, and bounded errors.

## 3. Desktop attachment workspace

- [x] 3.1 Extend the frontend client boundary, protocol types, mock adapter, and Gateway adapter for attachment listing, upload, and attachment-aware message submission.
- [x] 3.2 Implement the image picker with client-side type/size validation, object URL preview creation and cleanup, pending selection removal, and multiple-file handling.
- [x] 3.3 Replace the mock-only attachment panel action with upload controls, safe metadata display, registered/unavailable/error states, and local-preview versus Agent-load state separation.
- [x] 3.4 Integrate selected attachment IDs into the composer and clear or retain pending selections correctly across successful send, upload failure, and session switching.
- [x] 3.5 Preserve Simplified Chinese UI copy and mock-mode behavior while surfacing structured Gateway attachment errors without falling back to fake attachments.
- [x] 3.6 Add frontend smoke coverage for picker validation, upload request construction, attachment state rendering, session isolation, and attachment-aware message submission.

## 4. Verification and documentation

- [x] 4.1 Document attachment selection, Gateway startup, temporary-storage behavior, re-upload after Gateway restart, and the distinction between preview and `load_image`.
- [x] 4.2 Run focused attachment tests, the full Python regression suite, frontend smoke/build checks, and strict OpenSpec validation.
- [x] 4.3 Manually verify mock and Gateway browser workflows for selecting, previewing, uploading, switching sessions, sending an attachment-aware message, and showing unavailable-source feedback.
