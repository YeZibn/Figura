## MODIFIED Requirements

### Requirement: Gateway exposes named session lifecycle and transcript reads

The gateway SHALL provide JSON operations to list named sessions, create a named session, delete a named session, and retrieve a named session's completed text transcript. Session summaries SHALL include a stable opaque identifier, display name, update timestamp, and completed-run count. A transcript response SHALL contain session metadata and ordered user and assistant text records from completed runs. Deletion SHALL be addressed by session ID, reject active sessions, and remove all durable child records.

#### Scenario: Client lists available sessions

- **WHEN** a client requests the named-session collection
- **THEN** the gateway returns sessions in most-recently-updated order with bounded summary fields

#### Scenario: Client creates a session

- **WHEN** a client submits a valid unused session name
- **THEN** the gateway creates and returns an empty named session

#### Scenario: Client deletes an idle session

- **WHEN** a client deletes an existing session ID with no active run
- **THEN** the gateway removes the session, its runs, records, and attachment metadata, and returns a bounded success response

#### Scenario: Duplicate, missing, or busy session is explicit

- **WHEN** a client creates a duplicate name, requests an unknown session identifier, or attempts to delete a session with an active run
- **THEN** the gateway returns a structured conflict or not-found error without changing another session

#### Scenario: Transcript excludes unfinished runs

- **WHEN** a stored session has an interrupted or failed run
- **THEN** its transcript response excludes that run's partial conversation records

### Requirement: Gateway serves persistent attachment content by authorized reference

The Gateway SHALL expose a session-scoped content resource for registered attachments. Before returning bytes, it MUST verify session ownership, source existence, readability, supported media type, configured size limit, and unchanged content hash. Successful responses SHALL contain only bounded image bytes with the validated media type; failures SHALL use structured bounded errors without source paths.

#### Scenario: Authorized attachment content is fetched

- **WHEN** the active session requests content for an available attachment ID
- **THEN** the Gateway returns the source image bytes with its validated media type and no filesystem metadata

#### Scenario: Attachment content is unauthorized or invalid

- **WHEN** a different session requests the attachment, or the source is missing, changed, oversized, unreadable, or unsupported
- **THEN** the Gateway returns a bounded not-found, unauthorized, or unavailable error and no image bytes

## ADDED Requirements

### Requirement: Gateway deletes attachments and their source files

The Gateway SHALL provide a session-scoped attachment deletion operation. It SHALL verify ownership, remove the durable attachment metadata, and remove the corresponding source file only when the path is inside the managed attachment root. Deletion SHALL not remove files outside that root.

#### Scenario: Authorized attachment is deleted

- **WHEN** a client deletes an attachment ID belonging to an existing session
- **THEN** the Gateway removes its metadata and managed source bytes, and later content or load requests fail as unavailable or not found

#### Scenario: Cross-session attachment deletion is rejected

- **WHEN** a client uses an attachment ID belonging to another session
- **THEN** the Gateway returns a bounded not-found or unauthorized error and preserves the attachment

#### Scenario: Session deletion removes its attachment directory

- **WHEN** an idle session is deleted
- **THEN** the Gateway removes managed source files owned by that session after the durable session deletion succeeds
