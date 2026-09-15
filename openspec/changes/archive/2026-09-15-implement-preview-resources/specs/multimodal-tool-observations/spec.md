## ADDED Requirements

### Requirement: Visual observation references are client-loadable

The execution boundary SHALL expose each persisted visual observation with a
stable observation reference, owning session and run correlation, supported
media metadata, and an authorized preview resource while the observation is
available. An expired, missing, or unauthorized observation SHALL remain
renderable as bounded metadata without a broken or fabricated image URL.

#### Scenario: Persisted visual observation is previewable

- **WHEN** a run event contains a valid observation ID and the observation is
  still available to the owning session and run
- **THEN** the client can request the observation resource and display the
  returned image beside its originating tool call and caption

#### Scenario: Observation expires without leaking content

- **WHEN** an observation resource has expired or has been removed
- **THEN** the client displays its bounded caption and an explicit unavailable
  state, and no image bytes or local path are substituted

#### Scenario: Observation resources remain isolated

- **WHEN** a client changes the session or supplies an observation reference
  belonging to another run
- **THEN** the Gateway rejects the resource request and the client does not
  display the returned reference in the new session or run
