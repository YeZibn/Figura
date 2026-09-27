## Why

Figura's Provider boundary already accepts bounded image content, but a Run cannot yet retain or resolve image attachments. Adding a backend-owned attachment lifecycle first gives the Agent a durable, Session-authorized source for images before the Gateway and frontend are connected.

## What Changes

- Add backend image attachment storage with Session ownership, content validation, and private file storage; keep image bytes and local paths out of Run facts, events, and ordinary logs.
- Allow Run creation to persist ordered attachment IDs in the existing immutable `RunInput`, validate that every reference is available to the same Session, and include the ordered IDs in creation idempotency.
- Assemble the initial Agent user message from the persisted text and referenced images, enforcing the existing Provider image bounds before claiming or dispatching a provider attempt.
- Keep this change inside the Figura backend. Public upload routes, Gateway integration, frontend selection/preview, and UI work remain for a follow-up change.

## Capabilities

### New Capabilities
- `image-attachment-storage`: Store and resolve bounded, Session-owned image attachments for Figura Runs.

### Modified Capabilities
- `run-execution-core`: Permit authorized attachment references in immutable Run input and make them part of atomic creation and idempotency.
- `agent-react-execution`: Project persisted attachment bytes as image blocks in the initial user message and fail before provider dispatch when references or bounds cannot be satisfied.

## Impact

- Affected code: `src/figura/runtime/`, `src/figura/agent/`, and a new Figura-owned attachment storage module; the SQLite Run store needs an attachment metadata migration while binary files remain outside SQLite.
- Reuses the existing Provider image contract and limits in `src/figura/providers/`; no new provider or public transport contract is introduced.
- The later Gateway/frontend change will expose upload and selection flows over this backend capability.
