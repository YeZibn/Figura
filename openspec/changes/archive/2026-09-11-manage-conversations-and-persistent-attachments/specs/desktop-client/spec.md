## MODIFIED Requirements

### Requirement: User can inspect and switch sessions

The workspace SHALL display available sessions, identify the active session, allow the user to select another session or request a new session, and expose an explicit delete action for each session. Deletion SHALL require confirmation and SHALL keep the workspace in a valid empty or neighboring-session state after success.

#### Scenario: Active session is visible

- **WHEN** the workspace has loaded session data
- **THEN** the session list shows the active session with a distinct selected state and the conversation reflects that session

#### Scenario: User switches sessions

- **WHEN** the user selects another session
- **THEN** the active state changes and the conversation and attachment panels update to the selected session's data

#### Scenario: User starts a new session

- **WHEN** the user activates the new-session action and confirms a name
- **THEN** the new session becomes active with an empty or starter conversation and no stale attachment selection

#### Scenario: User deletes a session

- **WHEN** the user confirms deletion of an idle session
- **THEN** the client removes it from the list, selects a deterministic remaining session or shows the empty workspace, and clears stale run and attachment state

#### Scenario: Session deletion is rejected

- **WHEN** the Gateway reports that the session is busy or unavailable
- **THEN** the client keeps the session visible and shows bounded Simplified Chinese recovery feedback

### Requirement: User can inspect attachments

The workspace SHALL provide an attachment area showing attachment filename, media type, size, preview when available, and a visible state such as registered, unavailable, loaded, or observation available. Persistent previews SHALL be loaded through the Gateway's safe session-scoped resource, and registered attachments SHALL expose an explicit remove action.

#### Scenario: Attachment preview is distinct from model loading

- **WHEN** an attachment is available in the active session
- **THEN** the UI can show its Gateway or browser/client preview while separately indicating whether the Agent has loaded it

#### Scenario: Persistent attachment survives reload

- **WHEN** the active session is reopened after a frontend or Gateway restart and its source remains valid
- **THEN** the attachment metadata and image preview are restored without requiring the user to select the original local file again

#### Scenario: Attachment is unavailable

- **WHEN** the Gateway reports that an attachment source is missing or invalid
- **THEN** the UI shows an unavailable state and a re-upload recovery path without displaying a broken local path

#### Scenario: User removes an attachment

- **WHEN** the user confirms removal of a registered attachment
- **THEN** the client removes it from the panel and no longer includes its ID in a future message

#### Scenario: Attachment empty state

- **WHEN** the active session has no attachments
- **THEN** the attachment area shows an actionable empty state without disrupting conversation use
