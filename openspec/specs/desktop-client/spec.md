# desktop-client Specification

## Purpose

Provide a local desktop workspace for ChartAgent where users can inspect sessions, conversations, attachments, and execution details through a consistent React interface hosted by Tauri.

## Requirements

### Requirement: Desktop client starts into the ChartAgent workspace

The desktop client SHALL open a local ChartAgent workspace with clear session, conversation, and attachment areas. It SHALL be usable without provider credentials when running with mock data.

#### Scenario: Workspace opens offline

- **WHEN** the user starts the desktop client without a configured provider or backend
- **THEN** the workspace opens with mock content or an explicit empty state instead of failing to render

#### Scenario: Narrow window remains usable

- **WHEN** the desktop window is resized to a narrow width
- **THEN** the primary conversation and input controls remain readable and no major panel content overlaps

### Requirement: User-facing client content is Simplified Chinese

All user-visible interface labels, mock session names, sample messages, prompts, loading text, empty states, error messages, and interaction feedback SHALL use Simplified Chinese. Technical product names, code identifiers, protocol fields, and tool names MAY remain in English when needed for accuracy.

#### Scenario: Chinese workspace copy

- **WHEN** the desktop client renders its workspace in mock mode
- **THEN** visible labels and example content are presented in Simplified Chinese

#### Scenario: Technical identifiers remain recognizable

- **WHEN** the UI displays a tool name, attachment ID, or technical product name
- **THEN** it preserves the original identifier such as load_image, att_..., React, or Tauri rather than translating the identifier itself

### Requirement: User can inspect and switch sessions

The workspace SHALL display available sessions, identify the active session, and allow the user to select another session or request a new session through the UI.

#### Scenario: Active session is visible

- **WHEN** the workspace has loaded session data
- **THEN** the session list shows the active session with a distinct selected state and the conversation reflects that session

#### Scenario: User switches sessions

- **WHEN** the user selects another session
- **THEN** the active state changes and the conversation and attachment panels update to the selected session's data

#### Scenario: User starts a new session

- **WHEN** the user activates the new-session action and confirms a name
- **THEN** the new session becomes active with an empty or starter conversation and no stale attachment selection

### Requirement: User can inspect a conversation

The conversation area SHALL render user messages, Agent answers, and representative tool execution details as distinct visual items. Execution details SHALL be expandable and collapsible.

#### Scenario: Conversation renders mixed content

- **WHEN** a session contains user, assistant, tool, and visual-observation items
- **THEN** the UI renders them in chronological order with role-appropriate labels and content presentation

#### Scenario: Execution details are collapsed by default

- **WHEN** a conversation contains tool execution details
- **THEN** the primary answer remains easy to scan and the detailed tool items can be expanded without changing message order

#### Scenario: User enters a message

- **WHEN** the user enters non-empty text and activates send
- **THEN** the UI adds a user message and shows a pending/loading state for the assistant response

### Requirement: User can inspect attachments

The workspace SHALL provide an attachment area showing attachment filename, media type, size, preview when available, and a visible state such as registered, loaded, or observation available.

#### Scenario: Attachment preview is distinct from model loading

- **WHEN** an attachment is available in the active session
- **THEN** the UI can show its browser/client preview while separately indicating whether the Agent has loaded it

#### Scenario: Attachment empty state

- **WHEN** the active session has no attachments
- **THEN** the attachment area shows an actionable empty state without disrupting conversation use

### Requirement: Client state has a replaceable backend boundary

The desktop UI SHALL consume sessions, conversation items, attachments, and run actions through a replaceable client boundary so mock data can be replaced by the Python backend without changing core presentation behavior.

#### Scenario: Mock adapter drives the workspace

- **WHEN** the desktop client runs in mock mode
- **THEN** session switching, new-session interaction, message submission, and attachment display work without network or provider access

#### Scenario: Backend adapter preserves UI contracts

- **WHEN** a future backend adapter returns data using the defined client contracts
- **THEN** the same workspace components can render it without direct access to Python classes or SQLite
