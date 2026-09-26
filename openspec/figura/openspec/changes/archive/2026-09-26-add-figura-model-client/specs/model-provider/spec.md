## Purpose

Defines a server-side model-provider boundary for Figura so callers can use the selected multimodal models through one bounded contract while provider-specific request and continuation rules remain isolated.

## ADDED Requirements

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
Figura SHALL translate its bounded call input into the selected provider's supported OpenAI-compatible Chat Completions request. The input SHALL preserve message order, role, and tool-call/tool-result association. Image bytes SHALL be encoded only for the outbound request and SHALL NOT be written into ordinary logs or response metadata. A tool schema or input content that cannot be represented without weakening its constraints SHALL be rejected explicitly.

#### Scenario: Text conversation is sent
- **WHEN** a caller submits ordered text messages
- **THEN** the selected provider receives the same semantic roles and message order through its supported request format

#### Scenario: Authorized image bytes are included
- **WHEN** a caller supplies an in-memory image with a supported media type
- **THEN** Figura encodes it in the provider-supported image content format without publishing a local path or image bytes to logs

#### Scenario: Function tools are included
- **WHEN** a caller supplies supported function tool schemas
- **THEN** Figura sends the schemas and normalizes returned tool calls; if the provider cannot represent a schema faithfully, Figura rejects the request instead of relaxing it

### Requirement: Provider responses have a normalized shape
Figura SHALL normalize streaming and non-streaming completions into the same response shape containing assistant content, ordered tool calls, finish reason, and bounded usage metadata when provided. Normalized responses SHALL NOT retain an unrestricted raw SDK response as a persistence contract.

#### Scenario: Non-streaming completion is normalized
- **WHEN** a provider returns a non-streaming completion
- **THEN** Figura returns the normalized content, tool calls in provider order, finish reason, and available bounded usage counters

#### Scenario: Streaming completion is assembled
- **WHEN** a provider returns content and tool-call deltas as a stream
- **THEN** Figura assembles the deltas into the same normalized response shape and preserves tool-call ordering

### Requirement: Provider-private continuation data remains private and replayable
When a provider returns private reasoning content required or recommended for a later multi-turn request, Figura SHALL retain it as a provider-scoped continuation payload and SHALL pass it back unmodified when the next call requires it. Continuation data SHALL be excluded from ordinary assistant content, public events, and diagnostic logs. This provider layer SHALL expose continuation data only through its private call/result contract; durable storage is owned by a later execution-record change.

#### Scenario: Thinking tool call continues
- **WHEN** a provider returns a tool call with private reasoning content and a subsequent request continues that interaction
- **THEN** Figura replays the provider-required continuation data in the appropriate provider message field without merging it into assistant content

#### Scenario: Continuation data is projected publicly
- **WHEN** a response or diagnostic event is produced for an ordinary caller
- **THEN** provider-private continuation content is omitted while safe response content and bounded tool-call metadata remain available

### Requirement: Provider failures are bounded and do not trigger implicit retries or fallback
Figura SHALL classify provider failures using bounded provider-neutral metadata that distinguishes a known rejection from an unknown remote outcome. The SDK SHALL NOT retry requests implicitly, and Figura SHALL NOT automatically resend a request with an unknown outcome or switch to another provider. Raw provider exception bodies, credentials, and unrestricted response data SHALL NOT be exposed through the normalized failure.

#### Scenario: Request times out with an unknown remote outcome
- **WHEN** a timeout or transport interruption occurs without a definitive provider response
- **THEN** Figura reports an unknown outcome, does not automatically resend the request, and does not select a fallback provider

#### Scenario: Provider returns a definitive rejection
- **WHEN** a provider returns a definitive error response
- **THEN** Figura reports a bounded failure category and safe message without exposing raw credentials or exception content
