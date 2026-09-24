## Why

The desktop client can display a mock attachment, but users cannot select a real image, register it with the active Agent session, or send its opaque attachment ID with a message. The existing Python `AttachmentRegistry` already provides authorization and on-demand `load_image`; this change connects that capability to the React/Tauri workspace without putting image bytes into model messages or SQLite memory records.

## What Changes

- Add a real attachment picker in the React workspace with client-side image type and size checks and immediate local preview.
- Add loopback Gateway operations to register uploaded image bytes against a named session and list safe attachment metadata.
- Store uploaded bytes in a Gateway-managed ephemeral attachment area, while SQLite retains only safe attachment metadata and references.
- Allow a text message to carry authorized `attachment_id` values so the Agent receives metadata and may decide whether to call `load_image`.
- Show separate registered, loading, loaded, observation, unavailable, and upload-error states in the attachment panel.
- Preserve mock-mode attachment behavior and keep raw image bytes, local paths, credentials, and provider payloads out of JSON session transcripts and model history.
- Defer streamed tool progress, generated visual-observation events, Tauri process management, and durable cross-Gateway-restart upload storage to later changes.

## Capabilities

### New Capabilities

- `attachment-workspace`: Let the desktop client select, preview, register, and use authorized image attachments in Agent sessions.

### Modified Capabilities

None. The change uses the existing `attachment-access` contract and does not alter the Agent's `load_image` authorization or on-demand loading semantics.

## Impact

- Extends the Python Gateway protocol and service with attachment registration, metadata listing, and attachment-aware message input.
- Adds ephemeral local file management for uploaded bytes and bounded attachment metadata queries.
- Adds frontend file-input state, object URL cleanup, upload requests, attachment selection, and message composition integration.
- Reuses `AttachmentRegistry`, `SQLiteAgentMemory`, and the existing `load_image` tool without exposing their internal classes to React.
- Does not require a new Python dependency, a remote upload service, authentication, or a Tauri-only file-dialog API.
