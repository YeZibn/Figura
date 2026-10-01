## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Session deletion removes all owned attachment resources
Figura SHALL remove every attachment owned by a permanently deleted Session from attachment listings, metadata reads, and content resolution. Its private image files SHALL be moved out of active storage as part of the deletion transaction and permanently removed after commit; interrupted cleanup SHALL be reconciled without making deleted attachments readable.

#### Scenario: Remove Session-owned attachments
- **WHEN** a Session with one or more attachments is permanently deleted
- **THEN** none of its attachment metadata or image bytes can be read or listed, while attachments owned by other Sessions remain available

#### Scenario: Restore attachments when Session deletion rolls back
- **WHEN** the Session deletion transaction fails after its attachment files were staged
- **THEN** Figura restores the staged files and retains the Session's attachment metadata and readable content
