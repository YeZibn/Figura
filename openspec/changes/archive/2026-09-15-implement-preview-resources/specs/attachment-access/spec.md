## ADDED Requirements

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
