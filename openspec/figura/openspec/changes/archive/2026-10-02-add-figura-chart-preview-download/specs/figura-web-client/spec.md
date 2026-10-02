## MODIFIED Requirements

### Requirement: Figura mode exposes only supported workspace actions
Figura mode SHALL show Session creation, Session selection, Session deletion when permitted by its Gateway lifecycle rules, image attachment, Provider selection, Run submission, durable Run status, and committed chart-render output with full-size preview and download. It SHALL NOT offer evaluation workspaces, retry, resume, or interruption controls until their corresponding Figura Gateway capabilities are specified and available. This visibility rule SHALL NOT remove capabilities from the existing ChartAgent mode.

#### Scenario: Render the supported Figura capability set
- **WHEN** the user opens Figura mode
- **THEN** the workspace presents the supported Session, attachment, Provider, Run, and committed chart-render capabilities

#### Scenario: Use a ChartAgent-only capability
- **WHEN** the user opens ChartAgent mode
- **THEN** its existing evaluation, preview, and supported Run controls remain available under the existing client contract

### Requirement: Figura displays committed chart renders as read-only Run output
Figura mode SHALL display every committed successful chart render grouped under its originating Run, using the Figure title and PNG dimensions from safe render metadata. Each render SHALL have a thumbnail action that opens that exact PNG in the full-size preview with fit and zoom controls. The preview SHALL be dismissible with its close control or Escape and SHALL return focus to the thumbnail action. Each render SHALL provide a PNG download action for that same image; the download filename SHALL be derived safely from the Figure title and use a stable fallback when the title is empty or sanitizes to an empty name. A download failure SHALL produce a bounded user-visible error without disabling preview or other renders. The frontend SHALL load PNG bytes through the Figura client and SHALL NOT persist base64 image content, local paths, or raw tool results in browser storage. Chart renders SHALL remain read-only: the UI SHALL NOT add editing, review, publication, retry, or render-configuration controls. A Figure containing multiple child charts SHALL be previewed and downloaded as its complete rendered canvas. Existing ChartAgent and mock modes SHALL retain their current behavior.

#### Scenario: Display all committed chart renders
- **WHEN** a user opens a Figura Session containing committed successful chart renders in one or more Runs
- **THEN** the workspace displays every render grouped under its originating Run and labeled with its Figure title and PNG dimensions

#### Scenario: Open a selected chart render
- **WHEN** the user activates a render thumbnail
- **THEN** the full-size preview displays the PNG belonging to that render, with fit and zoom controls
- **AND** closing the preview restores focus to the thumbnail that opened it

#### Scenario: Preview a Figure with multiple child charts
- **WHEN** the selected render represents a Figure containing multiple child charts
- **THEN** the preview displays the complete composite Figure PNG with all rendered children

#### Scenario: Download a selected chart render
- **WHEN** the user activates a render's PNG download action
- **THEN** the browser downloads that render's PNG using a safe Figure-title-based filename without changing the committed render

#### Scenario: Report a failed render download
- **WHEN** the Figura client cannot retrieve the selected render's PNG for download
- **THEN** the UI reports a bounded download error and leaves the render preview and other render actions available

#### Scenario: Session has no committed chart renders
- **WHEN** the user opens a Figura Session with no committed successful chart renders
- **THEN** the workspace displays no empty chart-render gallery

#### Scenario: Preserve non-Figura frontend modes
- **WHEN** the frontend runs in mock or ChartAgent mode
- **THEN** it does not call Figura chart-render routes and preserves those modes' existing behavior
