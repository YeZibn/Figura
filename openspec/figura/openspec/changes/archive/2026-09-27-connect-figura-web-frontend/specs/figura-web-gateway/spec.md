## Purpose

Defines the local HTTP boundary that lets the browser operate Figura Sessions, image attachments, and durable Runs through existing Figura runtime capabilities. The boundary exposes bounded read projections and lifecycle events while keeping provider credentials, local paths, private continuation, and internal tool payloads inside Python.

## ADDED Requirements

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
The Gateway SHALL provide a Session-scoped Run summary, a history read after an optional event sequence, and an SSE stream that replays persisted events after a requested sequence before following new events. Event IDs SHALL preserve the Run ID and durable event sequence. Public event data SHALL use the existing lifecycle event kinds and allowlisted status fields only; it SHALL NOT contain input text, model response content, tool arguments/results, continuation, credentials, raw endpoints, or local paths. Terminal events SHALL close the stream after delivery.

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
