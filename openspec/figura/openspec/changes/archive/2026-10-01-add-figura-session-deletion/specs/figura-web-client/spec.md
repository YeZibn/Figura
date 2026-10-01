## ADDED Requirements

### Requirement: Figura Sessions can be deleted from the workspace
Figura mode SHALL expose an accessible delete action for every Session in the session list. Before deletion, the workspace SHALL require explicit confirmation that identifies the Session and explains that its conversation, Runs, attachments, Panels, and generated chart images will be permanently deleted. After Gateway success, the workspace SHALL remove the Session from the list; if it was selected, the workspace SHALL select a remaining Session or show the empty-session state. If deletion fails, the workspace SHALL retain the Session and its current view and display a bounded error.

#### Scenario: Confirm deletion of the selected Session
- **WHEN** the user confirms deletion of the selected Session and the Gateway completes the deletion
- **THEN** Figura mode removes the Session and its conversation from the workspace and selects another Session or shows the empty-session state

#### Scenario: Cancel Session deletion
- **WHEN** the user opens the delete confirmation and cancels it
- **THEN** the Session and its data remain unchanged

#### Scenario: Delete a Session that is not selected
- **WHEN** the user confirms deletion of a non-selected Session and the Gateway completes the deletion
- **THEN** the workspace removes only that Session and leaves the selected Session unchanged

#### Scenario: Keep the Session visible when deletion is rejected
- **WHEN** the Gateway rejects deletion because a Run is still running or the deletion otherwise fails
- **THEN** the workspace keeps the Session and its conversation visible and reports the bounded error
