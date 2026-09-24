## ADDED Requirements

### Requirement: Gateway serves generated chart artifacts by authorized reference

The Gateway SHALL persist and serve successful user-facing generated chart
artifacts through an opaque reference scoped to the owning session and run.
Artifact metadata SHALL include a bounded media type, byte count, dimensions,
chart type, and caption or title. Gateway responses SHALL not expose local
paths or raw image bytes in JSON.

#### Scenario: Generated chart is returned to its owning session

- **WHEN** a client requests a generated chart reference belonging to the
  active session and run
- **THEN** the Gateway returns the bounded image bytes with the declared media
  type and preserves the associated metadata

#### Scenario: Generated chart metadata is included in run history

- **WHEN** a run successfully produces a generated chart
- **THEN** its event history exposes the artifact reference and bounded
  metadata in execution order
- **AND** the client can distinguish it from a temporary model observation

#### Scenario: Generated chart survives ordinary reload

- **WHEN** a completed run is reopened within the configured artifact retention
  policy
- **THEN** the generated chart metadata remains readable and its artifact can
  be fetched through the authorized reference

#### Scenario: Generated chart access is isolated and bounded

- **WHEN** a different session, unknown reference, expired artifact, or an
  artifact over the configured output limit is requested
- **THEN** the Gateway returns a bounded not-found, unauthorized, expired, or
  unavailable error without revealing source paths or image content in JSON

#### Scenario: Session deletion removes generated charts

- **WHEN** the owning idle session is deleted
- **THEN** its generated chart artifacts and metadata are no longer readable
- **AND** another session's generated chart artifacts remain available
