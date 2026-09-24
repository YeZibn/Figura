## Purpose

Provide a local, browser-compatible gateway that lets the ChartAgent desktop client work with durable named Agent sessions and completed text runs without exposing Python internals or SQLite directly.

## ADDED Requirements

### Requirement: Gateway is available only as a local HTTP service

The system SHALL provide a versioned HTTP/JSON gateway bound to a loopback interface. It SHALL expose a health response and SHALL reject malformed JSON, unsupported methods, and unsupported routes with JSON error responses. The gateway MUST NOT bind to a non-loopback address by default.

#### Scenario: Local client verifies gateway availability

- **WHEN** a local desktop or browser client requests the gateway health endpoint
- **THEN** it receives a successful JSON response identifying a compatible gateway version

#### Scenario: Unsupported request is bounded

- **WHEN** a client sends malformed JSON, an unsupported method, or an unknown route
- **THEN** the gateway returns a JSON error with an appropriate client error status and no traceback or credential material

### Requirement: Gateway exposes named session lifecycle and transcript reads

The gateway SHALL provide JSON operations to list named sessions, create a named session, and retrieve a named session's completed text transcript. Session summaries SHALL include a stable opaque identifier, display name, update timestamp, and completed-run count. A transcript response SHALL contain session metadata and ordered user and assistant text records from completed runs.

#### Scenario: Client lists available sessions

- **WHEN** a client requests the named-session collection
- **THEN** the gateway returns sessions in most-recently-updated order with bounded summary fields

#### Scenario: Client creates a session

- **WHEN** a client submits a valid unused session name
- **THEN** the gateway creates and returns an empty named session

#### Scenario: Duplicate or missing session is explicit

- **WHEN** a client creates a duplicate name or requests an unknown session identifier
- **THEN** the gateway returns a structured conflict or not-found error without changing another session

#### Scenario: Transcript excludes unfinished runs

- **WHEN** a stored session has an interrupted or failed run
- **THEN** its transcript response excludes that run's partial conversation records

### Requirement: Gateway executes a text turn in a named session

The gateway SHALL accept a non-empty text message for a named session, execute the existing tool-capable Agent against that session, and return the refreshed completed transcript with the resulting final answer. The request SHALL be synchronous in this version.

#### Scenario: Successful text turn is returned

- **WHEN** a client submits valid text to an existing named session and the Agent completes
- **THEN** the response contains the submitted user text and final assistant answer in chronological order and increments the session's completed-run count

#### Scenario: Run failure is isolated

- **WHEN** provider setup or Agent execution fails for a submitted message
- **THEN** the gateway returns a bounded structured error and keeps prior completed session history readable

#### Scenario: Empty message is rejected before execution

- **WHEN** a client submits blank or whitespace-only text
- **THEN** the gateway returns a validation error and does not begin an Agent run

### Requirement: Gateway contract is safe and replaceable for the desktop client

Gateway responses SHALL use documented JSON fields independent of Python classes, SQLite rows, provider responses, raw traces, credentials, local file paths, attachment bytes, and generated image bytes. The desktop client SHALL be able to select the gateway adapter explicitly while preserving its mock adapter for offline development.

#### Scenario: Gateway mode replaces mock session operations

- **WHEN** the desktop client is configured for gateway mode and the local gateway is healthy
- **THEN** session listing, session creation, session reading, and text submission use the gateway contract rather than mock data

#### Scenario: Offline mock mode remains available

- **WHEN** the desktop client is configured for mock mode
- **THEN** it remains usable without a running gateway or provider configuration

#### Scenario: Sensitive and binary data are absent

- **WHEN** a gateway response represents a session or completed run that involved tools or attachments
- **THEN** it contains no credentials, raw provider payloads, local source paths, image bytes, data URLs, or unbounded trace payloads

