## MODIFIED Requirements

### Requirement: Attachment references survive named-session restart

Named sessions SHALL persist safe attachment references and their uploaded source bytes below the configured application-owned attachment directory. When no explicit attachment directory is configured, the source bytes SHALL be stored below the canonical data root in `attachments/`. The Gateway SHALL be able to validate and load a persistent source after restart using its prior attachment ID. Source bytes SHALL remain outside SQLite records and ephemeral generated observations SHALL remain process-local.

#### Scenario: Resumed session reloads an attachment

- **WHEN** a named session is resumed and the persistent source still passes validation
- **THEN** the model can load it again using its prior attachment ID and the workspace can request its safe preview

#### Scenario: Persistent source is missing or changed

- **WHEN** a named session is resumed but the referenced source no longer exists or fails its stored hash validation
- **THEN** the attachment remains safe metadata only, loading is rejected with a bounded error, and the client marks it unavailable

#### Scenario: Attachment data remains outside model history

- **WHEN** a persistent attachment is registered or reloaded
- **THEN** SQLite records and model history contain only bounded metadata and opaque IDs, never source image bytes or local paths

#### Scenario: Default attachment directory follows the data root

- **WHEN** a persistent attachment is registered without an explicit attachment directory
- **THEN** its source bytes are stored below the same canonical data root used by the session database
- **AND** changing the Gateway or CLI entrypoint does not change that default location
