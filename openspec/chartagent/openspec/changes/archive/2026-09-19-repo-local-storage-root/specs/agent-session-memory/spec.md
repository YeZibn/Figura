## MODIFIED Requirements

### Requirement: Named Agent sessions are durable and opt-in

The system SHALL allow named sessions to restore completed runs after restart; without a named session, Agent history SHALL remain process-local. Named-session state SHALL be stored in `sessions.db` below the canonical data root; when no explicit data root is configured, that root SHALL be the project-local `.chartagent/` directory.

#### Scenario: Named session resumes after restart

- **WHEN** a completed named session is opened again
- **THEN** its prior user, tool, and assistant information can enter bounded context

#### Scenario: Sessions are isolated

- **WHEN** two named sessions contain different histories
- **THEN** each exposes only records owned by that session

#### Scenario: Default session database is project-local

- **WHEN** a named session is created without an explicit data root or `CHARTAGENT_DATA_DIR`
- **THEN** its durable records are written to the project-local `.chartagent/sessions.db`
- **AND** the runtime does not create or update a second default database under `~/.chartagent`
