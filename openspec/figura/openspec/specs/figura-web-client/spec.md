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
Figura mode SHALL show Session creation, Session selection, image attachment, Provider selection, Run submission, and durable Run status. It SHALL NOT offer Session deletion, evaluation workspaces, generated-chart preview, retry, resume, or interruption controls until corresponding Figura Gateway capabilities are specified and available. This visibility rule SHALL NOT remove those capabilities from the existing ChartAgent mode.

#### Scenario: Render the initial Figura capability set
- **WHEN** the user opens Figura mode
- **THEN** the workspace presents only the Session, attachment, Provider, and Run actions served by Figura Gateway

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
Figura mode SHALL display committed successful chart-render previews grouped under their originating Runs, using the Figure title and PNG dimensions from safe render metadata. The frontend SHALL request PNG bytes on demand through the Figura client API and SHALL NOT persist base64 image content, local paths, or raw tool results in browser storage. Chart previews SHALL be read-only and SHALL NOT add editing, review, publication, retry, or render-configuration controls. Existing ChartAgent and mock modes SHALL retain their current behavior.

#### Scenario: Display committed chart renders
- **WHEN** the user opens a Figura Session containing Runs with committed chart renders
- **THEN** each preview is grouped under the Run that created it and labeled with the referenced Figure title

#### Scenario: Load a preview on demand
- **WHEN** a committed chart preview enters the visible UI region
- **THEN** the Figura client loads its PNG through the Session-scoped Gateway content route without storing the bytes in Session metadata or browser storage

#### Scenario: Session has no committed chart renders
- **WHEN** the user opens a Figura Session with no committed successful chart renders
- **THEN** the workspace displays the existing conversation and any other supported Run output without an empty chart-preview section

#### Scenario: Preserve non-Figura frontend modes
- **WHEN** the frontend runs in mock or ChartAgent mode
- **THEN** it does not call Figura chart-render routes and preserves those modes' existing behavior
