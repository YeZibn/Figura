# figura-web-client Specification

## Purpose

Defines the Figura mode of the existing React browser workspace. It lets a user operate the implemented Figura Session, attachment, Provider, and durable Run capabilities while keeping transport details in the API layer and preserving the current ChartAgent workspace contract.

## Requirements

### Requirement: The web workspace selects Figura through a separate client mode
The React application SHALL support a Figura browser mode backed by a Figura-specific client adapter and the Figura Web Gateway. Figura mode SHALL reuse the existing session, conversation, attachment, and run lifecycle UI where their behavior is supported. It SHALL preserve the existing ChartAgent and mock modes, `ChartAgentClient` compatibility surface, and Gateway/mock behavior. React components SHALL NOT issue Gateway HTTP or SSE requests directly.

#### Scenario: Start the Figura web workspace
- **WHEN** the frontend is started with Figura mode and a reachable Figura Gateway
- **THEN** it loads Figura Sessions and Provider availability through the Figura client adapter and renders the shared workspace

#### Scenario: Keep existing web modes available
- **WHEN** the frontend starts in mock or ChartAgent mode
- **THEN** it continues using its existing client and Gateway contracts without sending Figura API requests

#### Scenario: Figura Gateway is unavailable
- **WHEN** Figura mode cannot reach its configured Gateway
- **THEN** the workspace displays a bounded connection error and does not silently submit through the mock or ChartAgent client

### Requirement: The conversation view renders complete Session-level user messages
Figura mode SHALL list and create Sessions and SHALL render the persisted user input and accepted final answer for every Run in ascending Run ordinal order. It SHALL preserve the original text and attachment order and SHALL NOT create, truncate, summarize, or prune message history. Message keys SHALL derive from the owning Run and role. Internal provider continuation and raw tool-call arguments/results SHALL NOT be rendered as ordinary conversation messages.

#### Scenario: Open a Session with several Runs
- **WHEN** the user selects a Session with multiple terminal Runs
- **THEN** the conversation displays their user inputs and accepted answers in Run order, with the attachments associated with each user input

#### Scenario: Open a Session with a running Run
- **WHEN** the user opens a Session whose latest Run is still running
- **THEN** the persisted user input is visible and the Run status is restored without creating another Run

#### Scenario: Render a failed Run
- **WHEN** a Run has failed without an accepted final answer
- **THEN** the original user input and safe terminal message are visible without displaying private Provider or tool payloads

### Requirement: Provider selection reflects Figura's fixed allowlist and local configuration
Figura mode SHALL offer Qwen, DeepSeek, and MiMo using the fixed model IDs `qwen3.8-flash`, `deepseek-flash`, and `mimo-v2.6-flash`. It SHALL show configuration availability from the Gateway and SHALL prevent submission with an unavailable or unsupported Provider. The browser SHALL send the Provider ID only; it SHALL NOT receive or submit an API key, raw endpoint, or independently selected model ID.

#### Scenario: Choose an available Provider
- **WHEN** the user selects a configured Provider
- **THEN** the composer submits that Provider ID and the Gateway resolves its fixed model ID

#### Scenario: Provider configuration is missing
- **WHEN** the Gateway reports that a Provider is unavailable
- **THEN** the UI identifies that Provider as unavailable and does not submit a Run for it

### Requirement: The composer uploads Session-owned image attachments
Figura mode SHALL let the user add supported image files to a draft message, upload them to the selected Session, and submit their returned opaque IDs with the text. The UI SHALL show upload progress and bounded validation errors, retain successful uploads across Run completion, and allow removal only while the attachment is not referenced by a Run. The browser SHALL NOT place image bytes, local filesystem paths, or API credentials in persisted Session metadata.

#### Scenario: Submit text with uploaded images
- **WHEN** the user submits text with one or more successfully uploaded images
- **THEN** the Run request includes the opaque attachment IDs in the user's selected order

#### Scenario: Upload fails validation
- **WHEN** a selected file is unsupported, malformed, or too large
- **THEN** the UI reports a bounded upload error and excludes that attachment ID from Run creation

#### Scenario: Remove a referenced image
- **WHEN** the user tries to remove an image already referenced by a Run
- **THEN** the UI reflects the Gateway rejection and keeps the retained attachment available in the Session

### Requirement: Run controls follow Figura's durable lifecycle and event cursor
Figura mode SHALL create Runs with a fresh idempotency key per user submission, prevent a distinct second submission while a Session has a running Run, and restore a running Run after reload by reading durable state. It SHALL consume replayable lifecycle events from the last received sequence, reconnect through the shared run lifecycle controller, and reload Session detail after a terminal event. The UI SHALL present `running`, `completed`, `failed`, and `interrupted` outcomes and SHALL show a distinct safe waiting-for-reconciliation state when the Gateway projection reports an unresolved tool attempt. It SHALL NOT automatically create a replacement Run, replay an uncertain Provider call, or invoke an unresolved tool action.

#### Scenario: Follow a Run to completion
- **WHEN** a submitted Run emits ordered lifecycle events and reaches a terminal state
- **THEN** the UI converges on the durable Run status and reloads the Session's accepted answer

#### Scenario: Reconnect after a network interruption
- **WHEN** the browser loses its event stream and reconnects
- **THEN** it resumes after the last received sequence and catches up without duplicating Run lifecycle events

#### Scenario: Reload while a Run is active
- **WHEN** the browser reloads after Run creation but before a terminal event
- **THEN** it restores the existing Run and its event cursor without submitting the user message again

#### Scenario: A tool action requires reconciliation
- **WHEN** the Gateway reports that a still-running Run requires tool reconciliation
- **THEN** the UI shows that safe state and offers no automatic replay or duplicate Run action

### Requirement: Figura mode exposes only supported workspace actions
Figura mode SHALL show Session creation, Session selection, Session deletion when permitted by its Gateway lifecycle rules, image attachment, Provider selection, Run submission, durable Run status, and committed chart-render output with full-size preview and download. It SHALL NOT offer evaluation workspaces, retry, resume, or interruption controls until their corresponding Figura Gateway capabilities are specified and available. This visibility rule SHALL NOT remove capabilities from the existing ChartAgent mode.

#### Scenario: Render the supported Figura capability set
- **WHEN** the user opens Figura mode
- **THEN** the workspace presents the supported Session, attachment, Provider, Run, and committed chart-render capabilities

#### Scenario: Use a ChartAgent-only capability
- **WHEN** the user opens ChartAgent mode
- **THEN** its existing evaluation, preview, and supported Run controls remain available under the existing client contract

### Requirement: The Figura development launcher owns both local processes
`npm run dev:figura` SHALL start a Figura Gateway in the `agent` Conda environment and the Vite browser client, wait for Gateway health before reporting readiness, bind both services to loopback, and clean up both child process groups on normal exit, startup failure, SIGINT, and SIGTERM. The launcher SHALL load the project `.env` for the Gateway with existing process environment values taking precedence, pass only the Figura mode and Gateway URL to Vite, and use a Figura data directory defaulting to the Git-ignored project `.figura/` path. The default Figura Gateway and Vite ports SHALL be distinct from the existing ChartAgent Gateway and frontend ports.

#### Scenario: Start the Figura browser stack
- **WHEN** the user runs `npm run dev:figura`
- **THEN** the launcher starts the Python Figura Gateway and Vite client, waits for Figura health, and opens the client at its configured local URL

#### Scenario: Stop the development launcher
- **WHEN** the user sends SIGINT or SIGTERM to the launcher
- **THEN** both processes started by that launcher exit and release their owned ports

#### Scenario: Gateway fails before readiness
- **WHEN** the Figura Gateway exits or fails its health check during startup
- **THEN** the launcher stops Vite, reports a bounded startup error, and exits unsuccessfully

### Requirement: Figura displays committed Panels as read-only Run output
Figura mode SHALL display committed Panels associated with their originating Runs using Panel names and image previews retrieved through the Figura client. The frontend SHALL load Panel image bytes on demand through the client API and SHALL NOT persist base64 image content, local paths, or tool-result payloads in browser storage. Panel presentation SHALL provide no manual region editing, semantic review, or measurement controls in this change. Existing ChartAgent and mock modes SHALL retain their current behavior.

#### Scenario: Display Panels created by a completed Run
- **WHEN** the user opens a Figura Session containing a Run that committed Panel outputs
- **THEN** the UI displays each Panel's name and image preview grouped under its originating Run

#### Scenario: Load a Panel preview on demand
- **WHEN** a Panel enters the visible UI region
- **THEN** the Figura client fetches its image through the Session-scoped Gateway route and renders the returned PNG without storing image bytes in Session metadata

#### Scenario: Session has no committed Panels
- **WHEN** the user opens a Session with no committed Panel outputs
- **THEN** the UI continues to show the existing Session conversation and attachment UI without a Panel section

#### Scenario: Keep other frontend modes unchanged
- **WHEN** the frontend runs in mock or ChartAgent mode
- **THEN** it does not call Figura Panel routes and preserves those modes' existing client behavior

### Requirement: Figura displays committed chart renders as read-only Run output
Figura mode SHALL display every committed successful chart render grouped under its originating Run, using the Figure title and PNG dimensions from safe render metadata. Each render SHALL have a thumbnail action that opens that exact PNG in the full-size preview with fit and zoom controls. The preview SHALL be dismissible with its close control or Escape and SHALL return focus to the thumbnail action. Each render SHALL provide a PNG download action for that same image; the download filename SHALL be derived safely from the Figure title and use a stable fallback when the title is empty or sanitizes to an empty name. A download failure SHALL produce a bounded user-visible error without disabling preview or other renders. The frontend SHALL load PNG bytes through the Figura client and SHALL NOT persist base64 image content, local paths, or raw tool results in browser storage. Chart renders SHALL remain read-only: the UI SHALL NOT add editing, review, publication, retry, or render-configuration controls. A Figure containing multiple child charts SHALL be previewed and downloaded as its complete rendered canvas. Existing ChartAgent and mock modes SHALL retain their current behavior.

#### Scenario: Display all committed chart renders
- **WHEN** a user opens a Figura Session containing committed successful chart renders in one or more Runs
- **THEN** the workspace displays every render grouped under its originating Run and labeled with its Figure title and PNG dimensions

#### Scenario: Load a preview on demand
- **WHEN** a committed chart preview enters the visible UI region
- **THEN** the Figura client loads its PNG through the Session-scoped Gateway content route without storing the bytes in Session metadata or browser storage

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
- **THEN** the workspace displays the existing conversation and any other supported Run output without an empty chart-preview section

#### Scenario: Preserve non-Figura frontend modes
- **WHEN** the frontend runs in mock or ChartAgent mode
- **THEN** it does not call Figura chart-render routes and preserves those modes' existing behavior

### Requirement: Figura displays a concise per-Run tool execution timeline
Figura mode SHALL display a chronological user-facing timeline derived from the selected Run's Figura timeline projection. Each tool call, its attempts, and its result SHALL appear as one logical step, with a localized tool name when known, stable tool identifier, localized status, and a bounded failure summary when present. Tool-specific details SHALL be safe, allowlisted summaries rather than raw arguments or result payloads; they SHALL be collapsed by default in every state and SHALL load only when the user expands the step. Missing or unrecognized status SHALL be shown as unknown or reconciliation-required and SHALL NOT be inferred as success. Model-start/completion events SHALL NOT appear as ordinary timeline rows. Existing Panel and ChartRender galleries SHALL remain separate Run outputs. Timeline refreshes SHALL follow replayable `run_progress` events and durable event cursors; reload and reconnect SHALL restore committed steps without duplication or re-executing tools. Observation previews SHALL load on demand through the Figura client. The timeline SHALL NOT add manual tool invocation, measurement-scope selection, retry, resume, or interruption controls, and SHALL NOT change ChartAgent or mock behavior.

#### Scenario: Restore a completed Run timeline
- **WHEN** a user opens a Figura Session containing a completed Run with tool calls
- **THEN** the workspace displays its committed steps in tool-call order and keeps the final answer, Panel gallery, and ChartRender gallery in their existing areas

#### Scenario: Group a tool call and result into one step
- **WHEN** a Run has a tool-call fact, one or more attempt facts, and a matching result fact
- **THEN** the timeline presents one logical step with the current committed status rather than separate call and result rows

#### Scenario: Keep step details collapsed
- **WHEN** a tool step is pending, running, completed, failed, or reconciliation-required
- **THEN** its safe details and attempt history remain collapsed while the summary name, status, time, and necessary failure explanation remain visible

#### Scenario: Inspect a step on demand
- **WHEN** a user expands a tool step
- **THEN** the Figura client loads its bounded safe summaries and any authorized observation preview without loading those details for every timeline item in advance

#### Scenario: Refresh after a live tool-fact commit
- **WHEN** the active Run emits a replayable `run_progress` event
- **THEN** the client refreshes the durable timeline snapshot, merges by Run and call identity, and preserves the Run event cursor without duplicating a step

#### Scenario: Show unknown or unresolved status explicitly
- **WHEN** a call has no committed result or the result status is unsupported
- **THEN** the timeline displays a pending, running, unknown, or reconciliation-required state supported by the durable facts and never presents the call as successful

#### Scenario: Keep generated chart output separate
- **WHEN** a tool timeline contains `assemble_chart_figure` or `render_chart_figure`
- **THEN** those actions appear as tool steps while committed rendered PNGs remain visible in the separate ChartRender gallery

#### Scenario: Preserve other frontend modes
- **WHEN** the frontend runs in mock or ChartAgent mode
- **THEN** it continues to use its existing event contract and timeline behavior without calling Figura timeline routes

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
