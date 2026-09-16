# desktop-client Specification

## Purpose

Provide a local desktop workspace for ChartAgent where users can inspect sessions, conversations, attachments, and execution details through a consistent React interface hosted by Tauri.

## Requirements

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

#### Scenario: Chinese workspace copy

- **WHEN** the desktop client renders its workspace in mock mode
- **THEN** visible labels, example content, status feedback, and product-facing copy are presented in Simplified Chinese and identify the product as Figura

#### Scenario: Technical identifiers remain recognizable

- **WHEN** the UI displays a tool name, attachment ID, protocol field, or technical runtime identifier
- **THEN** it preserves the original identifier such as `load_image`, `att_...`, `React`, `Tauri`, or `chartagent` rather than translating the identifier itself

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

### Requirement: User can inspect a conversation

The conversation area SHALL render each completed or active Agent run as one
distinct chronological item containing, in order, the user request, its
expandable execution process, and its final result. Final Agent answers SHALL
be rendered as safe Markdown inside the final result area. Generated chart
artifacts SHALL be presented with the final result rather than as a duplicate
ordinary execution-timeline card, while the execution process SHALL retain a
compact event indicating that the chart was generated. The client SHALL use
the canonical run identifier returned by the Gateway to associate the user
request, assistant answer, execution events, and generated artifacts. New
server-backed runs SHALL NOT leave their user request or assistant answer in
the unassociated-message fallback merely because different layers generated
different local identifiers. The client SHALL preserve genuinely
unassociated legacy messages through a compatible fallback presentation.

#### Scenario: Conversation renders one Run in stable order

- **WHEN** a session contains a user request, an associated run, execution
  events, and a final answer
- **THEN** the UI renders one chronological Run item with the user request
  first, the expandable execution process second, and the final result last
- **AND** opening or closing the process does not change message order or lose
  any event

#### Scenario: Gateway Run identity associates the conversation

- **WHEN** the Gateway accepts a message and returns a Run identifier
- **THEN** the persisted user request, assistant answer, Run summary, and
  execution history use that same canonical identifier for association
- **AND** the UI renders the request and answer inside that Run instead of
  appending them as orphan messages

#### Scenario: Generated chart is shown as a final result

- **WHEN** an associated run produces one or more generated chart artifacts
- **THEN** the UI displays each available chart in the Run's final result area
- **AND** the execution process keeps only a bounded generated-chart event
  indicator instead of rendering the same chart as a second timeline card

#### Scenario: Run association survives live completion and reload

- **WHEN** a run receives an identifier during submission or is restored from
  persisted session data
- **THEN** the client associates the user request and assistant answer with
  that canonical run identifier and keeps them in the same Run item after
  completion or reload
- **AND** the client does not duplicate the user message or final answer

#### Scenario: Legacy messages remain visible

- **WHEN** a session contains a message that cannot be associated with a run
  identifier from the current or legacy data contract
- **THEN** the client renders the message in a compatible fallback position
- **AND** the message is not silently discarded while Run items are built

#### Scenario: Final answer renders Markdown

- **WHEN** the Agent answer contains Markdown headings, lists, tables,
  emphasis, links, or fenced code
- **THEN** the assistant answer displays those structures with safe styling in
  the final result area
- **AND** the source answer remains recoverable for copying or plain-text
  fallback

### Requirement: User can inspect persisted Agent runs

The desktop workspace SHALL display each Agent run as a compact execution
group with its status, duration or timestamps when available, event count, and
expand/collapse control. Inside the group it SHALL render ordered model,
tool, result, visual, and failure events, correlating tool evidence by call
identifier. A bounded or truncated tool result SHALL remain part of the
corresponding tool step and SHALL NOT become an unknown standalone step when
the outer tool identity is available.

#### Scenario: Completed run remains visible after reload

- **WHEN** the user reloads a session containing completed runs
- **THEN** the client restores their run summaries and can expand each one to
  inspect its persisted event history

#### Scenario: Tool status is correlated

- **WHEN** a tool call and its result share a call identifier
- **THEN** the UI shows one logical tool step whose status changes from running
  to success or failure
- **AND** its arguments, bounded result, and visual evidence are available
  behind the step disclosure control

#### Scenario: Truncated result remains in its tool step

- **WHEN** the Gateway marks a tool result body as truncated but preserves the
  originating tool name and call identifier
- **THEN** the UI keeps the result under the originating tool step
- **AND** it shows an explicit bounded or truncated-state indicator
- **AND** it does not render a separate “unknown tool” step

#### Scenario: Legacy or incomplete history is explicit

- **WHEN** a run has no recoverable events, has an event-history gap, or was
  interrupted by a Gateway restart
- **THEN** the UI shows an explicit unavailable, incomplete, or interrupted
  state
- **AND** it does not fabricate missing execution steps

### Requirement: User can inspect attachments

The workspace SHALL provide an attachment area showing attachment filename, media type, size, preview when available, and a visible state such as registered, unavailable, loaded, or observation available. Available image previews SHALL expose an explicit interactive preview trigger, persistent previews SHALL be loaded through the Gateway's safe session-scoped resource, and registered attachments SHALL expose an explicit remove action.

#### Scenario: Attachment preview is distinct from model loading

- **WHEN** an attachment is available in the active session
- **THEN** the UI can show its browser/client preview while separately indicating whether the Agent has loaded it

#### Scenario: Available attachment opens an interactive preview

- **WHEN** the user activates an available attachment image with a pointer or keyboard
- **THEN** the client opens the shared interactive preview for that attachment
- **AND** the attachment's filename, state, and remove action remain available when the preview closes

#### Scenario: Persistent attachment survives reload

- **WHEN** the active session is reopened after a frontend or Gateway restart and its source remains valid
- **THEN** the attachment metadata and image preview are restored without requiring the user to select the original local file again

#### Scenario: Attachment is unavailable

- **WHEN** the Gateway reports that an attachment source is missing or invalid
- **THEN** the UI shows an unavailable state and a re-upload recovery path without displaying a broken local path
- **AND** it does not open an interactive preview for the unavailable resource

#### Scenario: User removes an attachment

- **WHEN** the user confirms removal of a registered attachment
- **THEN** the client removes it from the panel and no longer includes its ID in a future message

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

### Requirement: User can observe a live Agent run

The desktop workspace SHALL start a run through the backend boundary and render
its current state as connecting, running, completed, failed, interrupted, or
unavailable. While a run is active, the workspace SHALL merge historical
replay and live events into one ordered execution group without replacing the
primary conversation with raw protocol data.

#### Scenario: User submits a Gateway-backed message

- **WHEN** the user sends non-empty text with zero or more selected attachment IDs in Gateway mode
- **THEN** the workspace immediately shows the user request and a running state, then consumes the associated run events until a terminal result

#### Scenario: Execution details arrive during a run

- **WHEN** the Gateway emits model, tool-call, or tool-result events
- **THEN** the workspace adds corresponding expandable execution details in
  order and keeps the main answer area scannable

#### Scenario: Run completes successfully

- **WHEN** the associated run emits a final answer
- **THEN** the workspace renders the Markdown assistant answer, marks the run
  completed, and refreshes the session summary without duplicating the user
  message or removing its execution group

#### Scenario: Run reconnects after an event-stream interruption

- **WHEN** the event connection becomes unavailable while the run is active
- **THEN** the workspace retains rendered events, requests missing events after
  the last known sequence when possible, and resumes the run state
- **AND** it reports an explicit history-gap state if replay is unavailable

#### Scenario: Run fails or Gateway becomes unavailable

- **WHEN** the run emits a bounded failure or the event connection becomes unavailable
- **THEN** the workspace marks the run as failed or unavailable, shows
  Simplified Chinese recovery feedback, and preserves all prior events and
  completed conversation content

### Requirement: User can inspect live visual observations

The workspace SHALL render visual-observation events with their tool name,
caption, and an authorized image preview when the observation resource is
available. Persisted observation metadata and artifact availability SHALL be
distinct from user-local attachment previews, and expired artifacts SHALL show
an explicit bounded state.

#### Scenario: Generated observation is available

- **WHEN** a run emits a visual observation with an authorized observation ID
- **THEN** the workspace retrieves and displays the bounded image preview
  alongside its caption and execution context
- **AND** the observation remains discoverable when the run is reopened if its
  persisted artifact is still within policy

#### Scenario: Observation resource is unavailable or expired

- **WHEN** the observation ID is missing, unauthorized, or its artifact has
  expired
- **THEN** the workspace shows the persisted caption and bounded unavailable
  state without displaying a broken URL or exposing a local path

### Requirement: Backend boundary supports live events in mock and Gateway modes

The client boundary SHALL expose equivalent run and event contracts for mock and Gateway adapters. Mock mode SHALL simulate a bounded ordered event sequence without network access, while Gateway mode SHALL use the local event stream and SHALL NOT silently fall back to mock events.

#### Scenario: Mock mode exercises the live-run UI

- **WHEN** the client runs in mock mode and the user submits a message
- **THEN** the UI receives simulated running, execution-detail, and terminal events through the same boundary used by Gateway mode

#### Scenario: Gateway mode uses real events

- **WHEN** the client runs in Gateway mode and the local Gateway is ready
- **THEN** run state, execution details, visual observations, and final answer are driven by the Gateway contract rather than fabricated client data

#### Scenario: Gateway mode is not ready

- **WHEN** Gateway mode is selected but the local runtime is unavailable
- **THEN** the client shows the unavailable state and does not silently switch to mock mode

### Requirement: Unified startup selects the real client boundary

When the documented one-step Gateway development command is used, the desktop client SHALL connect to the local Gateway event and session APIs without requiring a second manual frontend command. The client SHALL expose startup or connection failures in Simplified Chinese and SHALL preserve explicit mock mode as a separate offline workflow.

#### Scenario: One-step Gateway startup reaches the workspace

- **WHEN** the unified development command starts the Gateway and the React client successfully
- **THEN** the workspace opens in Gateway mode and subsequent messages use real Gateway runs and SSE events

#### Scenario: One-step Gateway startup fails

- **WHEN** the unified command cannot make the Gateway ready
- **THEN** the workspace shows the unavailable state and does not fabricate mock sessions, tool events, or answers

### Requirement: User can inspect generated chart outputs

The desktop workspace SHALL display a successful generated chart as a
user-facing output distinct from temporary model visual observations. It SHALL
show a bounded preview, chart type and basic metadata, provide an interactive
preview trigger for an available image resource, provide a download action
when the artifact is available, and retain the output in the run's execution
context.

#### Scenario: Generated chart is shown after a successful run

- **WHEN** a run produces a generated chart artifact with an authorized
  reference
- **THEN** the workspace displays its preview with its chart type, title or
  caption, and bounded size metadata
- **AND** the output is labeled as a generated chart rather than a source
  attachment or tool observation

#### Scenario: Generated chart opens an interactive preview

- **WHEN** the generated chart has a usable image resource and the user activates its preview with a pointer or keyboard
- **THEN** the workspace opens the shared interactive preview for the generated chart
- **AND** the chart metadata and generated-result status remain identifiable in the preview

#### Scenario: Generated chart can be downloaded

- **WHEN** the generated artifact is available to the active session
- **THEN** the workspace exposes an accessible download action that retrieves
  the artifact through the Gateway reference
- **AND** the action does not expose a local server path or provider data
- **AND** downloading remains independent from opening the interactive preview

### Requirement: Desktop client distinguishes tool, review, and publication presentation

The desktop client SHALL render tool execution, generated-chart review, and
publication as separate user-facing concepts. Tool names SHALL use the
canonical bilingual presentation mapping when available, while lifecycle event
labels SHALL use the event label catalog and structured state fields rather
than inferring review or publication from a generic status string.

#### Scenario: Tool step uses bilingual name mapping

- **WHEN** the execution timeline renders a known tool call
- **THEN** it displays the Simplified Chinese tool name together with its stable
  English identifier
- **AND** the identifier remains available for technical inspection and
  correlation

#### Scenario: Generated chart shows independent statuses

- **WHEN** the final result or execution timeline renders a generated chart
- **THEN** it can show tool completion, review state, and publication state
  separately
- **AND** a successful render is not labeled as verified or published unless
  the corresponding publication field allows it

#### Scenario: Review labels are semantically accurate

- **WHEN** the client receives `chart_review_started`,
  `chart_review_completed`, or a publication event
- **THEN** it uses distinct Simplified Chinese labels for review start, review
  completion, publication, and rejection
- **AND** it does not label `chart_review_started` as a completed review

#### Scenario: Generated chart survives an ordinary reload

- **WHEN** the user reopens a session containing a generated chart within the
  configured retention policy
- **THEN** the run history restores its metadata and the preview or download
  action can request the authorized artifact again

#### Scenario: Generated chart is unavailable

- **WHEN** the artifact is expired, missing, unauthorized, or the run reports a
  rendering failure
- **THEN** the workspace shows an explicit bounded unavailable or failed state
- **AND** it does not render a broken image or claim that generation succeeded

### Requirement: Desktop client provides a unified preview experience

The desktop client SHALL use one preview resource boundary for uploaded
attachments, visual observations, generated candidates, and published chart
artifacts and one interactive preview presentation in mock, browser
development, and Tauri Gateway modes. It SHALL resolve resources using the
active backend configuration, validate that the response is an expected image
media type, release temporary client URLs when their owner is no longer
displayed, preserve safe metadata when bytes are unavailable, and expose
consistent pointer, keyboard, zoom, fit, and close behavior for resources
that are available.

#### Scenario: All supported image kinds use the active Gateway

- **WHEN** the client renders an uploaded attachment, visual observation,
  candidate, or published chart in Gateway mode
- **THEN** it requests the resource through the active Gateway endpoint and
  does not construct a path from a local source filename

#### Scenario: All supported image kinds use the same interactive preview

- **WHEN** the user opens an available attachment, visual observation, candidate, or published chart
- **THEN** the client uses the same bounded preview presentation and controls for each image kind
- **AND** the surrounding session and run context remains intact

#### Scenario: Tauri-managed Gateway address is honored

- **WHEN** the Tauri runtime starts the Gateway on a configured loopback host
  or non-default port
- **THEN** preview requests use that runtime address consistently with session,
  run, and event requests

#### Scenario: Preview response is not an image

- **WHEN** a preview request returns an error document, unsupported media type,
  empty body, or malformed image bytes
- **THEN** the client does not render it as an image and shows a bounded
  unavailable or invalid-preview state
- **AND** it does not open an interactive preview for that resource

#### Scenario: Preview resource is released

- **WHEN** a preview component or open interactive preview is replaced, unmounted, closed, or its resource changes
- **THEN** the client releases any temporary object URL it created and does not
  retain stale image bytes for another session or run

#### Scenario: Mock preview remains compatible

- **WHEN** the client runs in mock mode
- **THEN** the same preview presentation states and interactive controls are
  exercised with local mock resources without requiring a Gateway or provider
  connection

### Requirement: User can select the provider for the next run

The desktop workspace SHALL provide a visible provider selector with the
supported choices `OpenAI（中转站）` and `Qwen（DashScope）`. The selector SHALL
send only the provider identifier through the Gateway API, preserve the
selection for the active session, and make clear when a changed selection
applies to the next run rather than an active run.

#### Scenario: Provider selector is visible

- **WHEN** the workspace is loaded in Gateway mode
- **THEN** the user can see the current provider and choose OpenAI or Qwen
  using Simplified Chinese labels

#### Scenario: Selection is used on submission

- **WHEN** the user selects Qwen and submits a message
- **THEN** the client sends `provider: "qwen"` with the run request and does not
  send API keys, endpoints, or arbitrary model parameters

#### Scenario: Selection survives session reload

- **WHEN** the active session is reloaded or revisited
- **THEN** the client restores the session's last effective provider when it is
  available, or falls back to the Gateway default with a clear state

#### Scenario: Unavailable provider is actionable

- **WHEN** Gateway health reports a provider as unavailable
- **THEN** the selector marks it unavailable or explains the bounded reason and
  prevents a misleading successful submission

### Requirement: Provider metadata is visible in run inspection

The workspace SHALL show the effective provider and model for a run when the
Gateway supplies them, while preserving the existing English machine
identifiers in any technical details.

#### Scenario: Run shows effective provider

- **WHEN** a run is accepted with provider metadata
- **THEN** its execution group or model-turn details show the corresponding
  Chinese provider label and model name

#### Scenario: Legacy run remains renderable

- **WHEN** a historical run has no provider metadata
- **THEN** the workspace renders it without fabricating a provider value
