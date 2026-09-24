## Purpose

Provide explicit, safe lifecycle controls for local Figura conversations so users can remove obsolete sessions while preserving database integrity and avoiding races with active Agent runs.

## ADDED Requirements

### Requirement: User can delete a named session

The Gateway and desktop client SHALL provide a delete operation addressed by the opaque session ID. The operation SHALL delete the session's durable transcript state, including its runs, records, and attachment metadata, and SHALL return a bounded success response without exposing local filesystem paths.

#### Scenario: Session is deleted

- **WHEN** the client requests deletion of an existing session that has no active Agent run
- **THEN** the Gateway removes the session and all cascaded durable records, and subsequent session lookup returns a session-not-found error

#### Scenario: Unknown session is deleted

- **WHEN** the client requests deletion with an unknown or malformed session ID
- **THEN** the Gateway returns a bounded not-found or validation error and does not modify any other session

#### Scenario: Active session is deleted from the UI

- **WHEN** the user activates the delete action for a session in the workspace
- **THEN** the client asks for explicit confirmation before issuing the delete request

### Requirement: Session deletion is protected against active runs

The Gateway SHALL reject deletion while an Agent run belonging to the target session is still active. The rejection SHALL use a stable bounded error code and SHALL leave the session, run, transcript, and attachment state unchanged.

#### Scenario: Session has a running Agent task

- **WHEN** a client requests deletion of a session with an active run
- **THEN** the Gateway returns a `session_busy` conflict and does not delete the session

#### Scenario: Session becomes inactive before deletion

- **WHEN** the target session has no active run at the deletion decision point
- **THEN** the Gateway completes the deletion as one lifecycle operation and does not leave an orphaned session record

### Requirement: Client recovers after deleting the active session

The desktop client SHALL remove a successfully deleted session from its session list and select a remaining neighboring session deterministically. If no sessions remain, it SHALL clear the conversation and show the existing empty workspace state.

#### Scenario: Another session remains

- **WHEN** the user deletes the active session and other sessions are available
- **THEN** the client selects the next available session, or the previous one when the deleted session was last, and refreshes its conversation and attachments

#### Scenario: Last session is deleted

- **WHEN** the user deletes the only session
- **THEN** the client shows no active session, clears pending attachment selection, and keeps the new-session action available
