## ADDED Requirements

### Requirement: Panel metadata and image content are readable through the owning Session
The Figura Web Gateway SHALL provide read-only Session-scoped access to committed Panel metadata and its independent PNG image. A Panel metadata response SHALL contain only `panelId`, originating `runId`, `sourceAttachmentId`, display `name`, and normalized polygon `points`; an image-content response SHALL return the validated PNG bytes with a non-cacheable response policy. The Gateway SHALL NOT expose storage paths, uncommitted Panels, tool arguments, or raw tool results.

#### Scenario: List Panels for a Session
- **WHEN** the browser requests Panels for an existing Session
- **THEN** the Gateway returns that Session's committed Panel metadata in originating Run and Panel creation order

#### Scenario: Read a Panel image
- **WHEN** the browser requests image content for a committed Panel through its owning Session
- **THEN** the Gateway returns the Panel's PNG bytes with an image media type and no-store cache policy

#### Scenario: Reject a Panel from another Session
- **WHEN** the browser requests a Panel ID through a Session that does not own it
- **THEN** the Gateway returns a bounded not-found response without disclosing the Panel's existence, metadata, or bytes

#### Scenario: Do not expose uncommitted Panel output
- **WHEN** a Panel image or metadata row was staged but its successful tool result has not committed
- **THEN** the Gateway does not include it in Session Panel reads
