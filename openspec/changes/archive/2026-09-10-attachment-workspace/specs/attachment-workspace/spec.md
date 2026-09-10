## Purpose

Let the ChartAgent desktop workspace accept real local images, register them as session-scoped attachments, preview them safely, and provide authorized attachment IDs to the Agent without eagerly loading image bytes into model context.

## ADDED Requirements

### Requirement: User can select and preview image attachments

The desktop client SHALL let the user choose one or more supported local image files for the active session. Before upload, it SHALL validate supported media type and configured size limits, show a local preview when the browser provides one, and preserve the selected file's filename and media type in the attachment view.

#### Scenario: Supported image is selected

- **WHEN** the user chooses a supported image file
- **THEN** the workspace shows a local preview and a pending attachment entry without sending the image to the model

#### Scenario: Unsupported or oversized image is rejected

- **WHEN** the user chooses a file with an unsupported media type or size above the configured limit
- **THEN** the workspace shows a Simplified Chinese validation error and does not upload or register the file

#### Scenario: User clears a pending image

- **WHEN** the user removes a selected image before sending it
- **THEN** the local preview is released and the image is absent from the next upload or message request

### Requirement: Gateway registers uploaded images within the active session

The local Gateway SHALL accept a bounded binary upload for an existing named session, validate its media type, size, readability, and content, and return an opaque session-scoped `attachment_id` with safe metadata. Uploaded bytes SHALL be kept only in Gateway-managed ephemeral attachment storage and SHALL NOT be returned in JSON responses, written into SQLite records, or sent to the model during registration.

#### Scenario: Image upload returns safe metadata

- **WHEN** the desktop client uploads a valid image for an active session
- **THEN** the Gateway returns an `att_...` identifier, filename, media type, byte count, and content hash without a local path or image payload

#### Scenario: Upload targets an unknown session

- **WHEN** the client uploads an image using an unknown or malformed session identifier
- **THEN** the Gateway rejects the request without creating an attachment or revealing filesystem details

#### Scenario: Uploaded bytes are isolated by session

- **WHEN** an attachment ID is used from a different session
- **THEN** attachment metadata and image loading are rejected as unauthorized

### Requirement: User can inspect registered attachment metadata

The workspace SHALL retrieve and display the active session's registered attachments, including filename, media type, byte count, attachment ID, preview availability, and a state such as registered, unavailable, or observation available. The metadata response SHALL not expose canonical local paths or raw image bytes.

#### Scenario: Registered attachment appears in the panel

- **WHEN** an upload succeeds for the active session
- **THEN** the attachment panel shows the safe metadata and keeps the local preview when it is still available

#### Scenario: Gateway restart loses only ephemeral upload content

- **WHEN** the Gateway restarts and an uploaded temporary source is no longer available
- **THEN** the session may retain safe attachment metadata, but the workspace marks the attachment unavailable and does not display a broken or unauthorized path

#### Scenario: Session switch clears stale attachment selection

- **WHEN** the user switches to another session
- **THEN** the attachment panel and pending attachment selection update to the new session without exposing attachments from the previous session

### Requirement: Messages carry authorized attachment references without eager loading

The desktop client SHALL be able to submit a text message with zero or more attachment IDs belonging to the active session. The Gateway SHALL provide safe attachment metadata to the Agent for that turn, and the Agent MAY call `load_image` when visual inspection is useful. Uploading or attaching an ID SHALL NOT force an image load or include image bytes in the initial model message.

#### Scenario: Text message includes an attachment

- **WHEN** the user sends a message with a registered attachment ID
- **THEN** the Agent receives the text and safe attachment metadata, and the response remains associated with that session

#### Scenario: Agent chooses to inspect the image

- **WHEN** the Agent calls `load_image` with the authorized attachment ID
- **THEN** the existing attachment-access validation runs and the image becomes available only on the next model turn

#### Scenario: Agent does not need visual inspection

- **WHEN** the Agent can answer without examining the image
- **THEN** it may respond without calling `load_image` and infrastructure does not force a model-visible image

### Requirement: Attachment failures are bounded and visible

Attachment registration, lookup, and load failures SHALL return bounded structured errors with stable error codes. The workspace SHALL show actionable Simplified Chinese feedback while preserving the conversation workflow. Errors MUST NOT reveal credentials, canonical paths, raw bytes, or unbounded provider details.

#### Scenario: Changed or missing temporary source

- **WHEN** an attachment source is missing, unreadable, changed, oversized, or no longer authorized
- **THEN** the Gateway rejects the operation with a bounded error and the workspace marks the attachment unavailable

#### Scenario: Upload failure does not corrupt the composer

- **WHEN** an upload fails after the user has entered a message
- **THEN** the workspace shows the upload error, keeps the message text available for correction, and does not submit a message with an unknown attachment ID

