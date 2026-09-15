# attachment-access Specification

## Purpose

Let the Agent register user-authorized image references and load them into multimodal context on demand without granting arbitrary filesystem access.

## Requirements

### Requirement: User image references become authorized attachments

Each valid image reference SHALL receive a session-scoped opaque ID and bounded metadata including filename, media type, byte count, and content hash. Registration SHALL NOT send image bytes to the model.

#### Scenario: Valid image is registered

- **WHEN** a supported local image is attached
- **THEN** the model receives safe metadata and an ID but no image content

### Requirement: Agent can load an authorized image as a tool

The registry SHALL provide load_image accepting only an ID owned by the active session. Success SHALL return safe metadata and an in-memory visual observation.

#### Scenario: Agent loads an image when useful

- **WHEN** the model calls load_image with a valid ID
- **THEN** the image becomes visible on the next model turn without entering JSON memory

#### Scenario: Model may choose not to load

- **WHEN** attachment metadata is present but visual inspection is unnecessary
- **THEN** the Agent may answer without infrastructure forcing a load

### Requirement: Attachment loading is validated and session-scoped

Before reading bytes, the system MUST verify ownership, existence, readability, media type, size, and unchanged content hash. Failures SHALL return bounded structured errors with no image payload.

#### Scenario: Changed or unauthorized file

- **WHEN** an ID is cross-session, missing, oversized, or its file changed
- **THEN** loading is rejected without revealing unauthorized paths or contents

### Requirement: Attachment references survive named-session restart

Named sessions SHALL persist safe attachment references and their uploaded source bytes below the configured application-owned attachment directory. The Gateway SHALL be able to validate and load a persistent source after restart using its prior attachment ID. Source bytes SHALL remain outside SQLite records and ephemeral generated observations SHALL remain process-local.

#### Scenario: Resumed session reloads an attachment

- **WHEN** a named session is resumed and the persistent source still passes validation
- **THEN** the model can load it again using its prior attachment ID and the workspace can request its safe preview

#### Scenario: Persistent source is missing or changed

- **WHEN** a named session is resumed but the referenced source no longer exists or fails its stored hash validation
- **THEN** the attachment remains safe metadata only, loading is rejected with a bounded error, and the client marks it unavailable

#### Scenario: Attachment data remains outside model history

- **WHEN** a persistent attachment is registered or reloaded
- **THEN** SQLite records and model history contain only bounded metadata and opaque IDs, never source image bytes or local paths

### Requirement: Gateway exposes an authorized attachment preview resource

The Gateway SHALL expose a session-scoped binary preview resource for each
registered image whose source passes the existing ownership, existence,
readability, media-type, size, and content-hash validation. The resource SHALL
return the original supported image media type and bytes without exposing a
local path, and SHALL reject missing, unauthorized, invalid, or changed
attachments with a bounded structured HTTP error.

#### Scenario: Available attachment preview is readable

- **WHEN** the client requests the preview resource for a valid attachment in
  its owning session
- **THEN** the Gateway returns the image bytes with the stored supported media
  type and a non-cacheable response policy

#### Scenario: Unauthorized attachment preview is rejected

- **WHEN** a client requests an attachment preview using an attachment ID from
  another session or an unknown ID
- **THEN** the Gateway returns a bounded not-found or authorization error and
  does not return image bytes or filesystem details

#### Scenario: Invalid attachment preview is explicit

- **WHEN** the registered source is missing, unreadable, changed, oversized, or
  no longer a supported image
- **THEN** the Gateway returns a bounded unavailable error and the metadata
  remains safe to display without a preview
