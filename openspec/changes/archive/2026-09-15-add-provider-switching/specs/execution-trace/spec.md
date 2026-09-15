## ADDED Requirements

### Requirement: Run trace preserves effective provider metadata

Execution history SHALL carry the effective provider and model as bounded
metadata on run-start or model-turn events and in historical run summaries when
available. The metadata SHALL be immutable for a run and MUST exclude secrets,
raw endpoint values, and provider response bodies.

#### Scenario: Provider is attached to model boundaries

- **WHEN** an Agent run starts a model turn
- **THEN** the event identifies the snapshotted provider and model alongside
  the existing turn metadata

#### Scenario: Provider metadata is safe

- **WHEN** trace events are persisted or returned to the desktop client
- **THEN** provider metadata is bounded and contains no API key, endpoint, or
  raw provider payload

#### Scenario: Provider remains stable after switching

- **WHEN** the user changes the frontend selection after a run starts
- **THEN** historical and live events for that run continue to report its
  original provider
