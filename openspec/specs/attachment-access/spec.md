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

Named sessions SHALL persist safe attachment references while ephemeral references remain process-local and no source or generated image bytes are persisted.

#### Scenario: Resumed session reloads an attachment

- **WHEN** a named session is resumed and the source still passes validation
- **THEN** the model can load it again using its prior attachment ID
