## Purpose

Let the Agent register user-authorized image references and load them into
multimodal context on demand without granting arbitrary filesystem access.

## ADDED Requirements

### Requirement: User image references become authorized attachments

The system SHALL register each valid user-provided image reference as a
session-scoped attachment with an opaque ID and bounded metadata including its
canonical path, media type, byte count, and content hash. Registration SHALL
NOT itself send image bytes to the model.

#### Scenario: Valid image is registered without eager upload

- **WHEN** a user attaches a supported local image to an Agent turn
- **THEN** the model receives its attachment ID and safe metadata but no image
  content until an image-loading tool is called

#### Scenario: Multiple attachments retain stable order

- **WHEN** one user turn references multiple valid images
- **THEN** each receives a distinct attachment ID and the model-visible metadata
  preserves the user's reference order

### Requirement: Agent can load an authorized image as a tool

The Agent tool registry SHALL provide `load_image`, accepting an attachment ID
owned by the active session. A successful call SHALL return safe structured
metadata plus an in-memory image observation that becomes visible to the model
on the next model turn.

#### Scenario: Agent loads an image when useful

- **WHEN** the model calls `load_image` with a valid attachment ID
- **THEN** the corresponding image becomes a tool-attributed multimodal
  observation without entering the JSON tool result or durable memory

#### Scenario: Agent reloads an earlier attachment

- **WHEN** the model calls `load_image` again during a later run of the same
  named session
- **THEN** the attachment can be loaded again after all current validations pass

#### Scenario: Model may choose not to load an attachment

- **WHEN** a turn includes attachment metadata but the model determines that no
  visual inspection is needed
- **THEN** the Agent may answer or call other tools without infrastructure
  forcing `load_image`

### Requirement: Attachment loading is session-scoped and validated

Before reading image bytes, the system MUST verify that the attachment belongs
to the active session, the canonical file still exists and is readable, its
content hash is unchanged, and its media type and byte count satisfy configured
limits. Validation failure SHALL produce a structured tool error with no image
payload.

#### Scenario: Attachment from another session is rejected

- **WHEN** `load_image` receives an attachment ID not owned by the active session
- **THEN** the tool returns a structured authorization error and does not reveal
  the other attachment's path or contents

#### Scenario: Changed file is not silently loaded

- **WHEN** the referenced path exists but its content hash differs from the
  registered hash
- **THEN** the tool returns a structured changed-file error and asks for a new
  user attachment instead of loading the new bytes

#### Scenario: Missing or oversized file is rejected

- **WHEN** the authorized file is missing, unreadable, unsupported, or exceeds
  the configured image size limit
- **THEN** the tool returns a bounded structured error and no visual observation

### Requirement: Attachment references survive named-session restart

The system SHALL persist safe attachment references for named sessions and
SHALL keep attachment references memory-only for ephemeral sessions. Persisted
references SHALL never include source image bytes.

#### Scenario: Resumed session can request a previous attachment

- **WHEN** a named session is resumed and a previously registered source image
  still passes ownership, existence, hash, media-type, and size validation
- **THEN** the Agent may call `load_image` with the previous attachment ID and
  receive a fresh in-memory visual observation

