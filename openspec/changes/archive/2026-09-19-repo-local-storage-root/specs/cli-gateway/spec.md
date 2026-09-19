## MODIFIED Requirements

### Requirement: Agent CLI manages opt-in named sessions

The Agent CLI SHALL support explicit create/resume, fresh-create, list, and confirmed-delete operations for named sessions. These options SHALL apply only to Agent mode; omitting them SHALL preserve ephemeral behavior. Listing and deletion SHALL work without starting the model. The CLI SHALL resolve session persistence through the canonical data root and SHALL accept an explicit data-root override without silently creating a second default store.

#### Scenario: Session lifecycle operations

- **WHEN** the user supplies session, new-session, list, or delete options
- **THEN** the CLI performs the requested bounded local operation, rejects conflicting options, and never overwrites an existing session on fresh-create

#### Scenario: Session deletion is source-safe

- **WHEN** the user confirms deletion of a named session
- **THEN** stored runs and attachment references are removed while source image files remain unchanged

#### Scenario: CLI and Gateway use the selected data root

- **WHEN** the user starts the CLI or Gateway with the same explicit data-root configuration
- **THEN** both can observe the same named sessions, attachments, and run records
- **AND** omitting the override selects the project-local `.chartagent/` root consistently
