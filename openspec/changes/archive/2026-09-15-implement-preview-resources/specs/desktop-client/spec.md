## ADDED Requirements

### Requirement: Desktop client provides a unified preview experience

The desktop client SHALL use one preview resource boundary for uploaded
attachments, visual observations, generated candidates, and published chart
artifacts in mock, browser development, and Tauri Gateway modes. It SHALL
resolve resources using the active backend configuration, validate that the
response is an expected image media type, release temporary client URLs when
their owner is no longer displayed, and preserve safe metadata when bytes are
unavailable.

#### Scenario: All supported image kinds use the active Gateway

- **WHEN** the client renders an uploaded attachment, visual observation,
  candidate, or published chart in Gateway mode
- **THEN** it requests the resource through the active Gateway endpoint and
  does not construct a path from a local source filename

#### Scenario: Tauri-managed Gateway address is honored

- **WHEN** the Tauri runtime starts the Gateway on a configured loopback host
  or non-default port
- **THEN** preview requests use that runtime address consistently with session,
  run, and event requests

#### Scenario: Preview response is not an image

- **WHEN** a preview request returns an error document, unsupported media type,
  empty body, or malformed image bytes
- **THEN** the client does not render it as an image and shows a bounded
  unavailable or invalid-preview state

#### Scenario: Preview resource is released

- **WHEN** a preview component is replaced, unmounted, or its resource changes
- **THEN** the client releases any temporary object URL it created and does not
  retain stale image bytes for another session or run

#### Scenario: Mock preview remains compatible

- **WHEN** the client runs in mock mode
- **THEN** the same preview presentation states are exercised with local mock
  resources without requiring a Gateway or provider connection
