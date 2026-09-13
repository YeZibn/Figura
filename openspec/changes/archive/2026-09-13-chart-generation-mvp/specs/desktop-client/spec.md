## ADDED Requirements

### Requirement: User can inspect generated chart outputs

The desktop workspace SHALL display a successful generated chart as a
user-facing output distinct from temporary model visual observations. It SHALL
show a bounded preview, chart type and basic metadata, provide a download
action when the artifact is available, and retain the output in the run's
execution context.

#### Scenario: Generated chart is shown after a successful run

- **WHEN** a run produces a generated chart artifact with an authorized
  reference
- **THEN** the workspace displays its preview with its chart type, title or
  caption, and bounded size metadata
- **AND** the output is labeled as a generated chart rather than a source
  attachment or tool observation

#### Scenario: Generated chart can be downloaded

- **WHEN** the generated artifact is available to the active session
- **THEN** the workspace exposes an accessible download action that retrieves
  the artifact through the Gateway reference
- **AND** the action does not expose a local server path or provider data

#### Scenario: Generated chart survives an ordinary reload

- **WHEN** the user reopens a session containing a generated chart within the
  configured retention policy
- **THEN** the run history restores its metadata and the preview or download
  action can request the authorized artifact again

#### Scenario: Generated chart is unavailable

- **WHEN** the artifact is expired, missing, unauthorized, or the run reports a
  rendering failure
- **THEN** the workspace shows an explicit bounded unavailable or failed state
- **AND** it does not render a broken image or claim that generation succeeded
