# figura-web-gateway Specification

## Purpose

Defines the local HTTP boundary that lets the browser operate Figura Sessions, image attachments, and durable Runs through existing Figura runtime capabilities. The boundary exposes bounded read projections and lifecycle events while keeping provider credentials, local paths, private continuation, and internal tool payloads inside Python.

## Requirements

### Requirement: Figura Web Gateway is restricted to the local browser boundary
The Figura Web Gateway SHALL bind only to a loopback address and SHALL accept browser requests only from explicitly configured local frontend Origins. It SHALL load Figura Provider configuration in the Python process, preserve process-environment precedence over the project `.env` file, and SHALL NOT return credentials, raw Provider endpoints, environment values, or local filesystem paths. A health read SHALL report local configuration availability without making a Provider network request.

#### Scenario: Read local Provider availability
- **WHEN** the browser reads Gateway health
- **THEN** the response identifies the Figura service and reports each allowlisted Provider's fixed model ID, configuration availability, and bounded reason code without contacting a Provider

#### Scenario: Reject a browser from an unconfigured Origin
- **WHEN** a browser sends a state-changing request from an Origin outside the configured allowlist
- **THEN** the Gateway rejects the request before changing Session, Attachment, or Run state

#### Scenario: Keep service and credential details private
- **WHEN** a health response or safe API error is serialized
- **THEN** it contains no API key, raw Provider endpoint, environment value, local path, or traceback

### Requirement: Sessions are created and read through bounded projections
The Gateway SHALL support Session listing, Session creation with an optional existing Session name, and Session-scoped reads. A Session projection SHALL expose only its opaque ID, name, creation/update timestamps, and Run count. A Session detail SHALL return ordered Runs, retained Attachment metadata, and a read-only message projection containing each Run's persisted user input and accepted final answer when one exists. Message identities SHALL be derived from their owning Run and role; the Gateway SHALL NOT persist a second message history. The projection SHALL preserve all Runs in the Session and SHALL NOT summarize, truncate, or prune them.

#### Scenario: Create and list a Session
- **WHEN** the browser creates a Session and then lists Sessions
- **THEN** the list contains the new opaque Session ID and its stored name and timestamps, and the detail reads empty history without creating a message record

#### Scenario: Project a multi-Run conversation
- **WHEN** a Session contains several completed, failed, or running Runs
- **THEN** its detail presents Runs in ascending ordinal order, each persisted user input once, and each accepted final answer once, while preserving attachment-ID order

#### Scenario: Read a Session using an ID owned elsewhere
- **WHEN** a request supplies an unknown Session ID or a Run ID owned by another Session
- **THEN** the Gateway returns a bounded not-found response without disclosing records or metadata from another Session

#### Scenario: Keep execution internals out of the conversation projection
- **WHEN** a Session detail is returned
- **THEN** it omits provider-private continuation, raw tool arguments and results, image bytes, and local attachment paths

### Requirement: Browser attachment operations preserve Session ownership
The Gateway SHALL allow the browser to upload, list, read, and delete supported image attachments only within their owning Session. Upload SHALL delegate content inspection, size validation, filename sanitization, and private storage to the Figura attachment capability. Metadata SHALL expose only opaque attachment ID, sanitized filename, verified media type, byte count, and creation time. Attachment deletion SHALL retain the existing rule that a Run-referenced attachment cannot be deleted.

#### Scenario: Upload and read a valid image
- **WHEN** the browser uploads valid supported image bytes to an existing Session
- **THEN** the Gateway returns bounded metadata with an opaque ID and the content endpoint returns the verified image bytes only for that Session

#### Scenario: Reject invalid or oversized image content
- **WHEN** the browser uploads empty, malformed, unsupported, or oversized image content
- **THEN** the Gateway returns a bounded validation error and leaves no retrievable attachment

#### Scenario: Reject cross-Session attachment access
- **WHEN** a browser lists, reads, deletes, or requests content for an attachment through a Session that does not own it
- **THEN** the Gateway rejects the request without revealing the attachment's existence or metadata

#### Scenario: Preserve an attachment referenced by a Run
- **WHEN** the browser attempts to delete an attachment already referenced by a Run input
- **THEN** the Gateway rejects deletion and retains both attachment metadata and content

### Requirement: Run creation is asynchronous, idempotent, and Session-scoped
The Gateway SHALL accept a bounded Run request containing nonempty text, an ordered list of owned attachment IDs, and an allowlisted `providerId`; it SHALL require an `Idempotency-Key` header and SHALL resolve the fixed model ID on the server. After the existing runtime atomically persists the Run, input, checkpoint, idempotency mapping, and creation event, the Gateway SHALL dispatch the same Run to the Figura Agent asynchronously and return its opaque Run ID and persisted status without waiting for Provider completion. It SHALL allow at most one running Run per Session, preserve same-key/same-payload idempotent replay, reject key reuse with a different payload, and SHALL NOT dispatch a Provider request from the HTTP handler itself.

#### Scenario: Start a Figura Run from the browser
- **WHEN** the browser submits a valid request with a configured Provider and an idempotency key
- **THEN** the Gateway returns an accepted response containing the persisted Run ID, Session ID, `running` status, Provider ID, and fixed model ID while Agent execution proceeds asynchronously

#### Scenario: Retry a request after losing the HTTP response
- **WHEN** the browser repeats the same Session request with the same idempotency key and payload
- **THEN** the Gateway returns the original Run and ensures its execution is scheduled at most once by the active Gateway process

#### Scenario: Reject conflicting or concurrent Run creation
- **WHEN** a key is reused with different text, attachment order, or Provider, or a distinct Run is requested while another Run in the Session is running
- **THEN** the Gateway returns a bounded conflict response without creating another Run or dispatching another execution

#### Scenario: Reject a missing Provider configuration or invalid input
- **WHEN** the request selects an unconfigured/unsupported Provider, supplies an invalid model selection, unknown Session, invalid attachment, empty text, or malformed idempotency key
- **THEN** the Gateway rejects the request before creating a Run or scheduling execution

### Requirement: Run history and SSE expose replayable lifecycle events
The Gateway SHALL provide a Session-scoped Run summary, a history read after an optional event sequence, and an SSE stream that replays persisted events after a requested sequence before following new events. Event IDs SHALL preserve the Run ID and durable event sequence. Public event data SHALL use the existing lifecycle event kinds and the `run_progress` marker with allowlisted fields only; a progress marker SHALL expose only the committed checkpoint revision and SHALL NOT contain input text, model response content, tool arguments/results, continuation, credentials, raw endpoints, or local paths. Terminal events SHALL close the stream after delivery; progress events SHALL keep it open.

#### Scenario: Catch up after reconnecting to a Run
- **WHEN** a browser reconnects with the last observed event sequence
- **THEN** the Gateway delivers every later persisted lifecycle event in sequence order without duplicating earlier events

#### Scenario: Recover history when events are written before subscription
- **WHEN** the Run creation or terminal event is already persisted before the browser opens SSE
- **THEN** the history read and stream replay deliver those events according to their durable sequence

#### Scenario: Deliver a terminal lifecycle event
- **WHEN** a Run completes, fails, or is interrupted
- **THEN** the stream delivers the corresponding terminal event with bounded status metadata and then closes

#### Scenario: Reject cross-Session Run event access
- **WHEN** the browser reads history or opens an event stream for a Run through a Session that does not own it
- **THEN** the Gateway rejects the request without returning the Run or its events

#### Scenario: Refresh timeline after a progress marker
- **WHEN** the browser receives a `run_progress` event
- **THEN** it can read the corresponding committed tool-fact snapshot through the Session-scoped timeline route, while the SSE payload itself remains free of tool details

### Requirement: Committed tool interactions are readable as a bounded Run timeline
The Gateway SHALL provide a Session-scoped timeline snapshot for one Run, an on-demand detail read for one tool call, and an on-demand observation-image read when a committed successful OCR or chart-measurement result has a reconstructable observation. The timeline SHALL be derived from that Run's committed `ToolCallFact`, `ToolAttemptStartedFact`, and `ToolResultFact` values; it SHALL NOT create duplicate timeline facts or include tool calls from another Run. Steps SHALL be ordered by durable tool-call sequence and grouped by call ID, with every attempt and any matching result associated with the originating call. Snapshot entries SHALL expose only bounded identity, tool name, timestamps, status, and a concise safe summary. Expanded details SHALL expose only bounded tool-specific summaries, attempt statuses and timestamps, safe error summaries, and typed source/observation references; they SHALL NOT return raw argument JSON or raw result JSON. Observation-image reads SHALL verify Session and Run ownership, require a successful supported OCR or measurement result and its authorized source, return a validated PNG with no-store headers, and SHALL NOT persist a reconstructed image. These routes SHALL NOT expose provider prompts, continuation, local paths, or image bytes in JSON.

#### Scenario: Read a Run timeline snapshot
- **WHEN** the browser reads the timeline for a Run containing committed tool calls
- **THEN** the Gateway returns one ordered summary per call, grouping its attempts and result without duplicating the tool payload in the snapshot

#### Scenario: Read one tool call's details
- **WHEN** the browser expands a timeline step for a call owned by the requested Session and Run
- **THEN** the Gateway returns only that call's bounded, allowlisted summaries, attempt statuses and timestamps, safe error summary, and available typed observation references

#### Scenario: Reflect a committed tool outcome
- **WHEN** a call has a committed successful or failed `ToolResultFact`
- **THEN** the timeline reports the corresponding completed or failed outcome and never infers success from a call or attempt-start fact alone

#### Scenario: Show an unresolved tool attempt safely
- **WHEN** a tool attempt has started without a committed result
- **THEN** the timeline reports it as running only while the current Gateway still owns the Run execution and otherwise reports a reconciliation-required or unknown state

#### Scenario: Show a call without an attempt
- **WHEN** a tool call has no committed attempt start
- **THEN** the timeline reports it as pending while the Run is active and not started when its Run is terminal

#### Scenario: Read a reconstructed observation image
- **WHEN** the browser requests an observation image for a successful OCR or chart-measurement call with an authorized source
- **THEN** the Gateway reconstructs and validates the annotated PNG on demand and returns it without storing a second image artifact

#### Scenario: Reject a call or image from another Session or Run
- **WHEN** the browser requests timeline details or an observation image using a call ID outside the requested Session and Run
- **THEN** the Gateway returns a bounded not-found response without disclosing the call, source, or image

#### Scenario: Restore the timeline after reload
- **WHEN** the browser reads a completed, failed, interrupted, or still-running Run after reload
- **THEN** the timeline is reconstructed from committed facts and does not invoke, replay, or reconcile any tool

#### Scenario: Omit raw tool payloads from details
- **WHEN** a browser reads the details for a known or unrecognized tool call
- **THEN** the Gateway returns only supported, bounded display summaries and never serializes raw arguments or result payloads

### Requirement: Gateway recovery follows durable Run checkpoint safety
On startup, the Gateway SHALL discover persisted running Runs and submit each to the existing Agent execution boundary once. Execution SHALL continue only from the durable checkpoint and existing recovery rules: a started Provider attempt with unknown outcome SHALL fail closed without resending, and an unresolved tool attempt SHALL remain undispatched for explicit reconciliation. A safe Run projection SHALL distinguish active Gateway execution from a Run that remains running because its next action requires reconciliation; it SHALL NOT mutate durable state merely to render that distinction.

#### Scenario: Resume a Run with a safe pending action
- **WHEN** the Gateway starts and finds a running Run whose checkpoint can continue under existing Agent rules
- **THEN** it schedules execution from that checkpoint without creating another Run or duplicating committed facts

#### Scenario: Recover an uncertain Provider attempt
- **WHEN** a started Provider attempt has no committed outcome after the prior execution owner exits
- **THEN** the Agent applies the existing unknown-outcome rule and does not send the Provider request again

#### Scenario: Surface an unresolved tool attempt
- **WHEN** Agent execution returns a still-running Run whose checkpoint requires tool reconciliation
- **THEN** the safe Run projection marks it as requiring reconciliation and the Gateway does not invoke or replay the tool

### Requirement: Panel metadata and image content are readable through the owning Session
The Figura Web Gateway SHALL provide read-only Session-scoped access to committed Panel metadata and its independent PNG image. A Panel metadata response SHALL contain only `panelId`, originating `runId`, `sourceAttachmentId`, display `name`, and normalized polygon `points`; an image-content response SHALL return the validated PNG bytes with a non-cacheable response policy. The Gateway SHALL NOT expose storage paths, uncommitted Panels, tool arguments, or raw tool results.

#### Scenario: List Panels for a Session
- **WHEN** the browser requests Panels for an existing Session
- **THEN** the Gateway returns that Session's committed Panel metadata in originating Run and Panel creation order

#### Scenario: Read a Panel image
- **WHEN** the browser requests image content for a committed Panel through its owning Session
- **THEN** the Gateway returns the Panel's PNG bytes with an image media type and no-store cache policy

#### Scenario: Reject a Panel from another Session
- **WHEN** the browser requests a Panel ID through a Session that does not own it
- **THEN** the Gateway returns a bounded not-found response without disclosing the Panel's existence, metadata, or bytes

#### Scenario: Do not expose uncommitted Panel output
- **WHEN** a Panel image or metadata row was staged but its successful tool result has not committed
- **THEN** the Gateway does not include it in Session Panel reads

### Requirement: Committed chart renders are readable through their owning Session
The Figura Web Gateway SHALL expose metadata only for committed successful chart renders and SHALL provide a read-only content endpoint addressed by the owning Session, render Run ID, and render tool-call ID. A render summary SHALL contain exactly `callId`, `figureRef` (`runId` and `callId`), `figureTitle`, `figureDigest`, `imageSha256`, `mediaType`, `byteCount`, `width`, and `height`. Summaries SHALL be grouped with their originating render Run in Session detail and Run history. Content reads SHALL verify that the Run belongs to the requested Session, that the referenced call has a committed successful `render_chart_figure` result, and that the stored PNG matches the committed metadata. Successful responses SHALL use `image/png`, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`. The Gateway SHALL NOT expose image paths, bytes in JSON, tool arguments, raw tool results, or uncommitted render files.

#### Scenario: Read a Session's committed render summaries
- **WHEN** the browser reads a Session containing one or more committed successful chart renders
- **THEN** each render appears in its originating Run's safe `chartRenders` summary with the documented metadata only

#### Scenario: Read a committed render image
- **WHEN** the browser requests a committed render's content through its owning Session and Run
- **THEN** the Gateway returns the validated PNG bytes with a non-cacheable image response

#### Scenario: Reject a cross-Session or unknown render reference
- **WHEN** the browser requests a render through a Session that does not own its Run or tool call
- **THEN** the Gateway returns a bounded not-found response without disclosing metadata or bytes

#### Scenario: Hide uncommitted render files
- **WHEN** a render image was staged or installed but no successful result has committed
- **THEN** neither Session detail nor the content endpoint exposes that render

#### Scenario: Detect a missing or corrupted render image
- **WHEN** committed metadata refers to a missing, unsafe, invalid, or digest-mismatched PNG
- **THEN** the Gateway returns a bounded storage or integrity error and no image bytes

### Requirement: Session deletion removes the owning Session as one bounded operation
The Gateway SHALL provide `DELETE /sessions/{sessionId}`. A successful deletion SHALL return `204` and make the Session, its Runs and execution facts, its attachment and Panel resources, and its ChartFigure render images unavailable through Figura APIs. The operation SHALL affect only the addressed Session. The Gateway SHALL reject an unknown Session with a bounded `404` response and SHALL reject deletion while any Run in the Session is `running` with a bounded `409` response. A rejected or failed deletion SHALL NOT be reported as successful. The operation SHALL follow the existing local-Origin and safe-error boundary.

#### Scenario: Delete a terminal Session
- **WHEN** the browser deletes an existing Session whose Runs are all terminal
- **THEN** the Gateway returns `204` and subsequent Session, Run, attachment, Panel, timeline, and chart-render reads cannot retrieve its data

#### Scenario: Preserve another Session during deletion
- **WHEN** the browser deletes one terminal Session while another Session has data
- **THEN** only resources owned by the addressed Session are removed and the other Session remains readable

#### Scenario: Reject deletion while a Run is running
- **WHEN** the browser deletes a Session containing a `running` Run
- **THEN** the Gateway returns a bounded `409` response and leaves the Session and all of its resources available

#### Scenario: Reject an unknown Session
- **WHEN** the browser deletes an unknown Session ID
- **THEN** the Gateway returns a bounded `404` response without disclosing other Session data

#### Scenario: Recover from a failed deletion
- **WHEN** persistent deletion cannot commit
- **THEN** the Gateway returns a bounded failure and the Session remains readable with its associated data intact
