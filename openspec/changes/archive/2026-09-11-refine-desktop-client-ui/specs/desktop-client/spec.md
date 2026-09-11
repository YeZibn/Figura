## MODIFIED Requirements

### Requirement: Desktop client starts into the ChartAgent workspace

The desktop client SHALL open a local Figura workspace with clear session, conversation, and attachment areas. The workspace SHALL establish a consistent visual hierarchy in which the active conversation is primary, session navigation and attachments are secondary, and run state remains visible. It SHALL be usable without provider credentials when running with mock data.

#### Scenario: Workspace opens offline

- **WHEN** the user starts the desktop client without a configured provider or backend
- **THEN** the workspace opens with mock content or an explicit empty state instead of failing to render, and the visible product identity is Figura

#### Scenario: Narrow window remains usable

- **WHEN** the desktop window is resized to a narrow width
- **THEN** the primary conversation, input controls, session navigation, and attachment content remain readable with no major panel content overlapping

### Requirement: User-facing client content is Simplified Chinese

All user-visible interface labels, mock session names, sample messages, prompts, loading text, empty states, error messages, and interaction feedback SHALL use Simplified Chinese and SHALL use Figura as the primary product name. Technical identifiers, protocol fields, file formats, and tool names MAY remain in English when needed for accuracy, but they SHALL NOT replace the Figura product identity in user-facing branding.

#### Scenario: Chinese Figura workspace copy

- **WHEN** the desktop client renders its workspace in mock mode or Gateway mode
- **THEN** visible labels, example content, status feedback, and product-facing copy are presented in Simplified Chinese and identify the product as Figura

#### Scenario: Technical identifiers remain recognizable

- **WHEN** the UI displays a tool name, attachment ID, protocol field, or technical runtime identifier
- **THEN** it preserves the original identifier such as `load_image`, `att_...`, `React`, `Tauri`, or `chartagent` rather than translating the identifier itself

## ADDED Requirements

### Requirement: Workspace provides a clear visual hierarchy

The desktop workspace SHALL visually distinguish the session navigation, primary conversation, attachment inspection, user input, execution details, visual observations, and service status. The primary answer and current user request SHALL remain easier to scan than raw tool details, and state distinctions SHALL not depend on color alone.

#### Scenario: Major workspace regions are distinguishable

- **WHEN** a session is loaded with messages and attachments
- **THEN** the user can identify the active session, primary conversation, attachment area, input area, and service state without relying on hidden navigation or ambiguous borders

#### Scenario: Answer remains primary during execution

- **WHEN** a conversation contains tool calls, tool results, or visual observations
- **THEN** the assistant answer and user request remain visually prominent while execution details remain available in a subordinate, expandable presentation

#### Scenario: Run states are understandable

- **WHEN** a run is connecting, running, completed, failed, or unavailable
- **THEN** the workspace presents the state with text and a distinguishable visual treatment, and the state does not cause surrounding content to shift unpredictably

### Requirement: Workspace interaction affordances are consistent and accessible

Interactive controls SHALL use consistent sizing, focus treatment, labels, and familiar iconography across session navigation, message execution details, attachment actions, dialogs, and message submission. Essential actions SHALL remain discoverable without depending exclusively on pointer hover.

#### Scenario: Controls remain discoverable on narrow or touch-oriented layouts

- **WHEN** the workspace is viewed at a narrow width or without hover input
- **THEN** essential session, attachment, dialog, and message actions remain visible or keyboard accessible and their text or accessible labels fit within their controls

#### Scenario: Focused controls are identifiable

- **WHEN** the user navigates the workspace with a keyboard and focuses an interactive control
- **THEN** the focused control has a visible focus treatment and its accessible name describes the action in Simplified Chinese or preserves a necessary technical identifier
