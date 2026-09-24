## ADDED Requirements

### Requirement: Attachment previews use one recoverable resource lifecycle

The desktop client SHALL load registered attachment previews through the client
backend boundary rather than trusting a local filesystem path or embedding
source bytes in session metadata. It SHALL represent loading, available,
unavailable, and invalid-media states separately, and SHALL offer a bounded
retry action when a transient resource request may recover.

#### Scenario: Registered attachment preview loads after reload

- **WHEN** the workspace restores an attachment whose Gateway preview resource
  is available
- **THEN** it displays the image preview and keeps the filename, media type,
  size, and attachment state visible

#### Scenario: Preview request is still loading

- **WHEN** the workspace has metadata for an available attachment but its
  preview request has not completed
- **THEN** it displays a loading state without mislabeling the attachment as
  unavailable or loaded into model context

#### Scenario: Preview failure can be retried safely

- **WHEN** a preview request fails with a retryable transport or temporary
  Gateway error
- **THEN** the workspace preserves the attachment metadata, shows bounded
  recovery feedback, and allows the user to retry without re-registering the
  same source

#### Scenario: Preview bytes are not an implicit model load

- **WHEN** the workspace successfully displays an attachment preview
- **THEN** it does not mark the attachment as loaded into model context or send
  a new Agent request solely because the client displayed the image
