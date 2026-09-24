## Why

The workspace currently exposes historical sessions but provides no way to remove them. Uploaded images are stored below a temporary Gateway directory and the browser only keeps short-lived local preview URLs, so a Gateway restart can leave durable session records pointing at missing source files. This change makes session and attachment lifecycle behavior complete for the local Figura workspace.

## What Changes

- Add a session deletion operation using the opaque session ID, with UI confirmation and predictable active-session recovery.
- Add attachment deletion for individual uploaded images and remove attachment files when their owning session is deleted.
- Replace process-start cleanup of uploaded images with persistent, application-owned attachment storage.
- Add a session-scoped attachment content/preview endpoint with ownership, file, media-type, size, and hash validation.
- Return accurate attachment availability metadata after Gateway restarts and preserve the existing lazy `load_image` model-tool boundary.
- Protect active sessions from deletion while one of their Agent runs is still executing.
- Keep mock and Gateway client contracts aligned and update the affected tests and documentation.

## Capabilities

### New Capabilities

- `session-management`: Delete a named session through the Gateway and client, including confirmation, active-session recovery, and lifecycle protection.

### Modified Capabilities

- `attachment-workspace`: Persist uploaded image sources, expose safe preview access, support attachment deletion, and retain usable metadata across Gateway restarts.
- `attachment-access`: Resolve and validate persistent session-scoped attachments without exposing local paths or image bytes in metadata.
- `python-gateway`: Add session and attachment deletion plus secure attachment-content routing and persistent storage behavior.
- `desktop-client`: Expose session and attachment deletion actions and render persistent/unavailable attachment states consistently.

## Impact

- Python Gateway service, HTTP router, attachment store, SQLite memory lifecycle, and run manager integration.
- React client API boundary, Gateway adapter, mock adapter, session sidebar, attachment panel, and confirmation dialogs.
- OpenSpec main specifications, Gateway tests, frontend smoke checks, README, and environment/data-directory documentation.
- No Tauri or Rust implementation changes are required.
