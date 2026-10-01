# image-attachment-storage Specification

## Purpose

Provides bounded, Session-owned image attachments that Figura can retain outside immutable Run records and resolve only for authorized Run inputs.

## Requirements

### Requirement: Image uploads are bounded and validated from their content
Figura SHALL accept an image upload only for an existing Session and only when the nonempty content is no larger than the Provider boundary's per-image limit. Figura SHALL identify the actual image format from the content, accept only JPEG, PNG, GIF, or WebP, and reject malformed or unsupported content without retaining an attachment. Caller-provided filenames and media types SHALL NOT determine the stored media type or storage path.

#### Scenario: Store a supported image
- **WHEN** an internal caller uploads a valid supported image within the per-image byte limit for an existing Session
- **THEN** Figura retains the image and returns bounded metadata with an opaque attachment ID and verified media type

#### Scenario: Reject invalid or oversized image content
- **WHEN** an upload is empty, malformed, uses an unsupported format, or exceeds the per-image byte limit
- **THEN** Figura rejects it without leaving an attachment record or retrievable image file

### Requirement: Attachment metadata and bytes remain within the backend boundary
Figura SHALL store image bytes outside Run execution records and public lifecycle events. Attachment metadata SHALL contain only the opaque attachment ID, owning Session ID, sanitized display filename, verified media type, actual byte count, and creation time. A storage path SHALL be derived from a server-controlled attachment ID and SHALL NOT be returned in attachment metadata, Run facts, events, or ordinary logs.

#### Scenario: Read metadata in the owning Session
- **WHEN** an internal caller lists or reads attachment metadata for the owning Session
- **THEN** Figura returns only the attachment's bounded metadata and never returns its local storage path or image bytes

#### Scenario: Access an attachment from another Session
- **WHEN** an internal caller lists, reads, or deletes an attachment using a Session that does not own it
- **THEN** Figura rejects the operation without disclosing the attachment's metadata, bytes, or existence

### Requirement: Attachment bytes can be resolved only through an owning Session reference
Figura SHALL resolve image bytes only when both the owning Session ID and opaque attachment ID match a retained, validated attachment. Returned bytes SHALL be provided only to internal Agent request assembly and SHALL NOT be written into durable Run input, ordinary logs, or lifecycle events.

#### Scenario: Resolve an attachment for its owning Session
- **WHEN** Agent request assembly resolves a retained attachment using its owning Session ID and attachment ID
- **THEN** Figura returns the validated bytes and verified media type for the in-memory Provider request

#### Scenario: Resolve a missing or unavailable attachment
- **WHEN** Agent request assembly references an unknown attachment or its retained file is missing or unreadable
- **THEN** Figura reports a bounded storage or reference failure and returns no image bytes

### Requirement: Referenced attachments remain available for immutable Runs
Figura SHALL prevent standalone deletion of an attachment referenced by any retained Run input. A Session aggregate deletion MAY remove referenced attachments only as part of permanently deleting the owning Session and all its Runs, and only when no Run in that Session is running. Successful deletion SHALL make the attachment metadata and bytes unavailable. A failed standalone or aggregate deletion SHALL NOT be reported as successful.

#### Scenario: Delete an unreferenced attachment
- **WHEN** an internal caller deletes an attachment that is not referenced by a committed Run input in its owning Session
- **THEN** Figura removes its metadata and binary content and no longer returns it from list, read, or resolve operations

#### Scenario: Preserve an attachment referenced by a retained Run
- **WHEN** an internal caller attempts to delete an attachment referenced by any Run input without deleting its owning Session aggregate
- **THEN** Figura rejects deletion and keeps the metadata and image bytes available to that Run

#### Scenario: Delete a referenced attachment with its Session
- **WHEN** a terminal Session is permanently deleted together with all of its Runs
- **THEN** Figura removes the Session's attachment metadata and bytes even when a deleted Run input referenced them

#### Scenario: Reconcile interrupted file cleanup
- **WHEN** Figura opens the attachment store after a process interruption during upload, standalone deletion, or Session deletion
- **THEN** Figura restores files whose metadata transaction did not commit and removes staged or orphaned files whose metadata no longer exists

### Requirement: Session deletion removes all owned attachment resources
Figura SHALL remove every attachment owned by a permanently deleted Session from attachment listings, metadata reads, and content resolution. Its private image files SHALL be moved out of active storage as part of the deletion transaction and permanently removed after commit; interrupted cleanup SHALL be reconciled without making deleted attachments readable.

#### Scenario: Remove Session-owned attachments
- **WHEN** a Session with one or more attachments is permanently deleted
- **THEN** none of its attachment metadata or image bytes can be read or listed, while attachments owned by other Sessions remain available

#### Scenario: Restore attachments when Session deletion rolls back
- **WHEN** the Session deletion transaction fails after its attachment files were staged
- **THEN** Figura restores the staged files and retains the Session's attachment metadata and readable content
