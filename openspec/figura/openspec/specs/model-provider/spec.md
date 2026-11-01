## Purpose

Defines a server-side model-provider boundary for Figura so callers can use the selected multimodal models through one bounded contract while provider-specific request and continuation rules remain isolated.

## Requirements

### Requirement: Provider and model selection is explicit and allowlisted
Figura SHALL accept only the configured provider/model pairs `qwen` / `qwen3.8-flash`, `deepseek` / `deepseek-flash`, and `mimo` / `mimo-v2.6-flash`. A provider call SHALL use an explicitly selected provider and SHALL NOT infer selection from available credentials or silently switch providers. Credentials and raw endpoints SHALL remain in server-side configuration and SHALL NOT be returned in availability metadata, ordinary responses, events, or logs.

#### Scenario: Call uses an allowed provider and model
- **WHEN** a caller selects one of the configured provider/model pairs and the provider has a configured local profile
- **THEN** Figura resolves the matching server-side profile and sends the request to that provider and model

#### Scenario: Caller selects an unsupported provider or model
- **WHEN** a caller selects an unknown provider or a model not allowlisted for that provider
- **THEN** Figura rejects the call before sending a network request and does not fall back to another provider

#### Scenario: Provider credentials are missing
- **WHEN** the selected provider has no configured credential or required endpoint
- **THEN** the provider is reported as unavailable with a bounded reason code and no secret or raw endpoint is disclosed

### Requirement: Provider calls support bounded text, image, and function-tool inputs
Figura SHALL translate bounded inputs into the selected Provider's explicitly supported OpenAI-compatible Chat Completions contract. Each allowlisted Provider/model SHALL declare whether native multimodal tool results are supported. A supported result SHALL preserve one tool_call_id and ordered text/image parts inside that logical tool result. Figura SHALL preserve message order, role, exact opaque tool-call/result association, and originating image resource identity. Internal TOOL image content SHALL NOT be prohibited by a universal user-only rule.

The shared execution-payload contract SHALL protect complete structured requests without generic message, instruction, tool, call, image-count or small text/Schema limits. Optional completion limits SHALL be positive integers when selected and otherwise omitted; there SHALL be no universal 4096 default or 131072 maximum. Provider-specific parameter names, genuine ranges and capabilities SHALL stay local to its contract. Images SHALL retain existing source byte/decode protections and be encoded only for outbound requests, never ordinary logs or metadata.

Unsupported tool-result images or unrepresentable schemas SHALL cause an explicit local unsupported_capability before attempt claim or dispatch. Figura SHALL NOT silently append plain user images, strip media, relax constraints, switch Provider/model or select another API protocol. Known unsupported visual tool configurations SHALL be rejected before the ordinary model action that would expose the visual tool surface. Native capability enablement for each configured model SHALL have exact-contract evidence and an actual image-recognition acceptance result; HTTP success alone SHALL NOT be reported as visual acceptance.

#### Scenario: Text conversation is sent
- **WHEN** a caller submits ordered text messages
- **THEN** the selected provider receives the same semantic roles and message order through its supported request format

#### Scenario: Authorized image bytes are included
- **WHEN** a caller supplies an in-memory image with a supported media type
- **THEN** Figura encodes it in the provider-supported image content format without publishing a local path or image bytes to logs

#### Scenario: Function tools are included
- **WHEN** a caller supplies supported function tool schemas
- **THEN** Figura sends the schemas and normalizes returned tool calls; if the provider cannot represent a schema faithfully, Figura rejects the request instead of relaxing it

#### Scenario: Omit an unspecified completion limit
- **WHEN** no explicit completion limit is configured for the selected Provider
- **THEN** Figura omits the output-limit wire parameter and uses the Provider service default without reserving cumulative Run tokens

#### Scenario: Honor an explicit supported completion limit
- **WHEN** a positive explicit output limit is supported by the selected Provider
- **THEN** Figura sends it using that Provider's actual parameter contract rather than a universal maximum

#### Scenario: Send a native multimodal tool result
- **WHEN** the selected fixed model supports native tool-result images and a result has one or more authorized image blocks
- **THEN** the outbound tool result contains its text and image parts under the same tool_call_id with no extra plain user image message

#### Scenario: Reject unsupported tool-result images without fallback
- **WHEN** the selected model cannot faithfully represent multimodal tool results
- **THEN** Figura reports unsupported_capability before claim or dispatch and neither drops images nor changes the result into ordinary user input

#### Scenario: Validate real image visibility before enabling support
- **WHEN** a Provider accepts a minimal two-call image task whose textual metadata does not reveal the answers
- **THEN** support is enabled only after the model identifies each image's visible feature and associates it with the correct call, with unsupported or unverified models explicitly reported
### Requirement: Provider responses have a normalized shape
Figura SHALL send every Provider request through the streaming response contract. Each configured Provider/model pair SHALL explicitly declare streaming support; a Provider without that capability SHALL be rejected before network dispatch. Figura SHALL assemble a successful terminal stream into one normalized response containing assistant content, ordered complete tool calls, finish reason, bounded usage metadata when provided, and private continuation data when provided. A response SHALL be accepted only after a valid terminal event. Figura SHALL NOT retain an unrestricted SDK response or partial stream as a persistence contract, and SHALL NOT use a non-streaming fallback.

#### Scenario: Normalize a complete assistant stream
- **WHEN** a supported Provider emits assistant content and a valid terminal event
- **THEN** Figura returns one normalized response with ordered content, finish reason, and available bounded usage metadata

#### Scenario: Assemble fragmented tool calls
- **WHEN** a supported Provider emits tool-call IDs, names, and JSON arguments across multiple stream events
- **THEN** Figura assembles them by Provider call index, preserves call order, and returns only complete tool calls in the normalized response

#### Scenario: Reject a Provider without streaming capability
- **WHEN** a selected Provider/model pair does not declare support for the streaming contract
- **THEN** Figura rejects the request before network dispatch and does not fall back to a non-streaming request

#### Scenario: Reject an incomplete stream
- **WHEN** the transport closes or the stream ends without a valid terminal event
- **THEN** Figura returns a bounded incomplete-stream failure and does not expose a normalized response

#### Scenario: Keep Provider-private continuation data separate
- **WHEN** a complete stream includes Provider-private continuation data
- **THEN** Figura returns it only in the private continuation field and excludes it from assistant text and public stream events

### Requirement: Provider-private continuation data remains private and replayable
When a provider returns private reasoning content required or recommended for a later multi-turn request, Figura SHALL retain it as a provider-scoped continuation payload and SHALL pass it back unmodified when the next call requires it. Continuation data SHALL be excluded from ordinary assistant content, public events, and diagnostic logs. This provider layer SHALL expose continuation data only through its private call/result contract; durable storage is owned by a later execution-record change.

#### Scenario: Thinking tool call continues
- **WHEN** a provider returns a tool call with private reasoning content and a subsequent request continues that interaction
- **THEN** Figura replays the provider-required continuation data in the appropriate provider message field without merging it into assistant content

#### Scenario: Continuation data is projected publicly
- **WHEN** a response or diagnostic event is produced for an ordinary caller
- **THEN** provider-private continuation content is omitted while safe response content and bounded tool-call metadata remain available

### Requirement: Provider failures are bounded and do not trigger implicit retries or fallback
Figura SHALL classify provider failures using bounded provider-neutral metadata that distinguishes a known rejection from an unknown remote outcome. The SDK SHALL NOT retry requests implicitly, and the transport SHALL NOT retry implicitly. The durable execution owner alone SHALL apply the explicit provider-request-retries contract; Figura SHALL NOT switch to another provider. Failure metadata SHALL distinguish outcome certainty, recognized temporary category and safe optional retry delay. Unrecognized exceptions SHALL NOT automatically be classified temporary. Raw provider exception bodies, credentials, and unrestricted response data SHALL NOT be exposed through the normalized failure.

#### Scenario: Request times out with an unknown remote outcome
- **WHEN** a timeout or transport interruption occurs without a definitive provider response
- **THEN** Figura reports an unknown outcome, does not itself resend the request or select fallback, and allows only the durable owner to assess a guarded generation-only replacement

#### Scenario: Provider returns a definitive rejection
- **WHEN** a provider returns a definitive error response
- **THEN** Figura reports a bounded failure category and safe message without exposing raw credentials or exception content

#### Scenario: Configure a long I/O timeout
- **WHEN** a Provider timeout is finite and positive but exceeds 600 seconds
- **THEN** Figura accepts the configuration without imposing a Run deadline; the timeout retains its I/O waiting semantics
