## MODIFIED Requirements

### Requirement: Gateway registers uploaded images within the active session

The local Gateway SHALL accept a bounded binary upload for an existing named session, validate its media type, size, readability, and content, and return an opaque session-scoped `attachment_id` with safe metadata. Uploaded bytes SHALL be stored below a persistent application-owned attachment directory and SHALL NOT be returned in JSON responses, written into SQLite records, or sent to the model during registration.

#### Scenario: Image upload returns safe metadata

- **WHEN** the desktop client uploads a valid image for an active session
- **THEN** the Gateway returns an `att_...` identifier, filename, media type, byte count, content hash, and availability metadata without a local path or image payload

#### Scenario: Upload survives a Gateway restart

- **WHEN** the Gateway restarts after a valid image upload and the persistent attachment directory remains accessible
- **THEN** the attachment remains registered and loadable through its prior ID

#### Scenario: Upload targets an unknown session

- **WHEN** the client uploads an image using an unknown or malformed session identifier
- **THEN** the Gateway rejects the request without creating an attachment or revealing filesystem details

#### Scenario: Uploaded bytes are isolated by session

- **WHEN** an attachment ID is used from a different session
- **THEN** attachment metadata, content access, and image loading are rejected as unauthorized or not found

### Requirement: User can inspect registered attachment metadata

The workspace SHALL retrieve and display the active session's registered attachments, including filename, media type, byte count, attachment ID, preview availability, and a state such as registered, unavailable, or observation available. The metadata response SHALL not expose canonical local paths or raw image bytes. When an attachment is available, the workspace SHALL be able to obtain its preview through the Gateway's session-scoped content resource.

#### Scenario: Registered attachment appears after reload

- **WHEN** an active session with a persistent attachment is loaded after a page or Gateway restart
- **THEN** the attachment panel shows its safe metadata and a preview backed by the Gateway content resource when validation succeeds

#### Scenario: Persistent source is unavailable

- **WHEN** attachment metadata exists but its source is missing, unreadable, changed, or no longer valid
- **THEN** the workspace marks the attachment unavailable, avoids a broken or unauthorized path, and offers the existing re-upload recovery

#### Scenario: Session switch clears stale attachment selection

- **WHEN** the user switches to another session
- **THEN** the attachment panel and pending attachment selection update to the new session without exposing attachments from the previous session

### Requirement: User can remove a registered attachment

The workspace SHALL provide an explicit remove action for a registered attachment. A successful removal SHALL remove it from the active attachment list and prevent it from being selected for future messages; the historical transcript MAY retain a bounded attachment ID reference but SHALL no longer be able to load the source.

#### Scenario: Registered attachment is removed

- **WHEN** the user confirms removal of an attachment that is not being used by an active upload
- **THEN** the Gateway deletes its metadata and source bytes, and the workspace removes it from the attachment panel

#### Scenario: Attachment removal fails

- **WHEN** the Gateway rejects attachment removal or cannot complete the storage operation
- **THEN** the workspace keeps the attachment entry visible, shows a bounded Simplified Chinese error, and does not remove its selection state optimistically

## ADDED Requirements

### Requirement: Attachment previews use a safe session-scoped resource

The client SHALL construct previews from a Gateway content URL addressed by the active session ID and opaque attachment ID. Preview requests SHALL not contain or expose canonical local paths, and an unavailable response SHALL be rendered as an unavailable attachment state.

#### Scenario: Available attachment preview is loaded

- **WHEN** the client requests content for an authorized available attachment
- **THEN** the Gateway returns the bounded image bytes with the validated media type and the workspace displays the image

#### Scenario: Preview is unauthorized or invalid

- **WHEN** the client requests content for an attachment from another session or whose source fails validation
- **THEN** the Gateway returns a bounded error and the workspace displays the unavailable state without exposing source details
