## MODIFIED Requirements

### Requirement: User can inspect attachments

The workspace SHALL provide an attachment area showing attachment filename, media type, size, preview when available, and a visible state such as registered, unavailable, loaded, or observation available. Available image previews SHALL expose an explicit interactive preview trigger, and persistent previews SHALL be loaded through the Gateway's safe session-scoped resource. Registered attachments SHALL expose an explicit remove action.

#### Scenario: Attachment preview is distinct from model loading

- **WHEN** an attachment is available in the active session
- **THEN** the UI can show its browser/client preview while separately indicating whether the Agent has loaded it

#### Scenario: Available attachment opens an interactive preview

- **WHEN** the user activates an available attachment image with a pointer or keyboard
- **THEN** the client opens the shared interactive preview for that attachment
- **AND** the attachment's filename, state, and remove action remain available when the preview closes

#### Scenario: Persistent attachment survives reload

- **WHEN** the active session is reopened after a frontend or Gateway restart and its source remains valid
- **THEN** the attachment metadata and image preview are restored without requiring the user to select the original local file again

#### Scenario: Attachment is unavailable

- **WHEN** the Gateway reports that an attachment source is missing or invalid
- **THEN** the UI shows an unavailable state and a re-upload recovery path without displaying a broken local path
- **AND** it does not open an interactive preview for the unavailable resource

#### Scenario: User removes an attachment

- **WHEN** the user confirms removal of a registered attachment
- **THEN** the client removes it from the panel and no longer includes its ID in a future message

#### Scenario: Attachment empty state

- **WHEN** the active session has no attachments
- **THEN** the attachment area shows an actionable empty state without disrupting conversation use

### Requirement: User can inspect generated chart outputs

The desktop workspace SHALL display a successful generated chart as a user-facing output distinct from temporary model visual observations. It SHALL show a bounded preview, chart type and basic metadata, provide an interactive preview trigger for an available image resource, provide a download action when the artifact is available, and retain the output in the run's execution context.

#### Scenario: Generated chart is shown after a successful run

- **WHEN** a run produces a generated chart artifact with an authorized reference
- **THEN** the workspace displays its preview with its chart type, title or caption, and bounded size metadata
- **AND** the output is labeled as a generated chart rather than a source attachment or tool observation

#### Scenario: Generated chart opens an interactive preview

- **WHEN** the generated chart has a usable image resource and the user activates its preview with a pointer or keyboard
- **THEN** the workspace opens the shared interactive preview for the generated chart
- **AND** the chart metadata and generated-result status remain identifiable in the preview

#### Scenario: Generated chart can be downloaded

- **WHEN** the generated artifact is available to the active session
- **THEN** the workspace exposes an accessible download action that retrieves the artifact through the Gateway reference
- **AND** the action does not expose a local server path or provider data
- **AND** downloading remains independent from opening the interactive preview

#### Scenario: Generated chart survives an ordinary reload

- **WHEN** the user reopens a session containing a generated chart within the configured retention policy
- **THEN** the run history restores its metadata and the preview or download action can request the authorized artifact again

#### Scenario: Generated chart is unavailable

- **WHEN** the artifact is expired, missing, unauthorized, or the run reports a rendering failure
- **THEN** the workspace shows an explicit bounded unavailable or failed state
- **AND** it does not render a broken image, offer an unusable interactive preview, or claim that generation succeeded

### Requirement: Desktop client provides a unified preview experience

The desktop client SHALL use one preview resource boundary and one interactive preview presentation for uploaded attachments, visual observations, generated candidates, and published chart artifacts in mock, browser development, and Tauri Gateway modes. It SHALL resolve resources using the active backend configuration, validate that the response is an expected image media type, release temporary client URLs when their owner is no longer displayed, preserve safe metadata when bytes are unavailable, and expose consistent pointer, keyboard, zoom, fit, and close behavior for resources that are available.

#### Scenario: All supported image kinds use the active Gateway

- **WHEN** the client renders an uploaded attachment, visual observation, candidate, or published chart in Gateway mode
- **THEN** it requests the resource through the active Gateway endpoint and does not construct a path from a local source filename

#### Scenario: All supported image kinds use the same interactive preview

- **WHEN** the user opens an available attachment, visual observation, candidate, or published chart
- **THEN** the client uses the same bounded preview presentation and controls for each image kind
- **AND** the surrounding session and run context remains intact

#### Scenario: Tauri-managed Gateway address is honored

- **WHEN** the Tauri runtime starts the Gateway on a configured loopback host or non-default port
- **THEN** preview requests use that runtime address consistently with session, run, and event requests

#### Scenario: Preview response is not an image

- **WHEN** a preview request returns an error document, unsupported media type, empty body, or malformed image bytes
- **THEN** the client does not render it as an image and shows a bounded unavailable or invalid-preview state
- **AND** it does not open an interactive preview for that resource

#### Scenario: Preview resource is released

- **WHEN** a preview component or open interactive preview is replaced, unmounted, closed, or its resource changes
- **THEN** the client releases any temporary object URL it created and does not retain stale image bytes for another session or run

#### Scenario: Mock preview remains compatible

- **WHEN** the client runs in mock mode
- **THEN** the same preview presentation states and interactive controls are exercised with local mock resources without requiring a Gateway or provider connection
