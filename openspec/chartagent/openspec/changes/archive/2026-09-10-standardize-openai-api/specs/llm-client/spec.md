## MODIFIED Requirements

### Requirement: OpenAI-compatible endpoint configuration layering

The client SHALL resolve each connection and behavior setting with the
precedence: explicit call or constructor parameter > canonical environment
variable loaded from `.env` via `python-dotenv` > legacy DashScope environment
variable > built-in default. The canonical credential, endpoint, and model
variables SHALL be `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`.
For migration compatibility, `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`, and
`DASH_MODEL` SHALL remain accepted only as lower-priority fallbacks. The
default endpoint SHALL be the standard OpenAI API base URL, and an explicit
`base_url` SHALL override every environment or default value. A configured
model SHALL be usable when a call omits `model`.

#### Scenario: Explicit parameters take precedence over canonical and legacy environment variables

- **WHEN** a caller supplies an explicit endpoint and API key while both
  `OPENAI_*` and `DASHSCOPE_*` values are present
- **THEN** the client uses the explicit values for the connection

#### Scenario: Canonical OpenAI environment variables are preferred

- **WHEN** no explicit endpoint, credential, or model is supplied and both
  canonical and legacy variables are set
- **THEN** the client uses `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and
  `OPENAI_MODEL`

#### Scenario: Legacy variables remain a migration fallback

- **WHEN** no canonical variable is set but the corresponding DashScope
  variable is present
- **THEN** the client derives that setting from the legacy variable and can
  construct the configured call target

#### Scenario: Defaults are used when nothing is configured

- **WHEN** no explicit parameter and no relevant environment variable is set
- **THEN** the client uses the built-in standard OpenAI endpoint and default
  timeout/retry values, while requiring a credential before a real call

### Requirement: OpenAI Chat Completions request contract

Every client invocation SHALL use the OpenAI Chat Completions contract with a
model, `messages`, and an explicit `stream` value. Optional tools SHALL be
sent through the standard `tools` field. Streaming calls SHALL request usage
through `stream_options.include_usage`. A caller-provided reasoning level SHALL
be sent as `reasoning_effort`, and a caller-provided output limit SHALL be
sent as `max_completion_tokens`. The standard request path MUST NOT
automatically send the Qwen-specific `extra_body.enable_thinking` or the
deprecated `max_tokens` field.

#### Scenario: Plain standard request is constructed

- **WHEN** a caller sends messages without tools, reasoning, or an output
  limit
- **THEN** the provider receives `model`, `messages`, and `stream`, with no
  provider-specific thinking body and no deprecated token-limit field

#### Scenario: Standard tools and reasoning are propagated

- **WHEN** a caller supplies tool definitions and `reasoning_effort`
- **THEN** the provider receives the same definitions under `tools` and the
  reasoning level under `reasoning_effort`

#### Scenario: Streaming requests include usage metadata

- **WHEN** a caller makes a streaming invocation
- **THEN** the provider receives `stream_options` with
  `include_usage` set to true, and the normalized result can expose the final
  usage object when the provider returns one

### Requirement: Normalized output structure

Every Chat Completions invocation SHALL return one normalized structure
exposing `content`, `reasoning`, `tool_calls` (a list), `finish_reason`,
`usage`, and `raw`. `raw` MUST preserve the original provider response, or
the ordered response chunks for a streaming invocation, so provider-specific
details are not lost. When a field is not applicable, the corresponding
field MUST be present with a stable empty or absent value. Standard usage
metadata, including any provider-reported reasoning-token details, MUST be
preserved without requiring textual reasoning to be available.

#### Scenario: Normal plain-text reply

- **WHEN** the model answers with plain content and no tool calls
- **THEN** the returned structure has `content` populated, `reasoning` empty,
  `tool_calls` empty, and `finish_reason`/`usage` reflecting the response

#### Scenario: Standard response without textual reasoning

- **WHEN** a provider returns ordinary content and usage metadata but no
  textual reasoning field
- **THEN** `reasoning` is an empty string, usage remains available, and no
  missing-field exception occurs

#### Scenario: Raw response is always available

- **WHEN** any invocation completes successfully
- **THEN** `raw` contains the untouched response object or ordered stream
  chunks so the caller can recover fields not normalized by the client

### Requirement: Tool definition calls with correct tool_calls propagation

The client SHALL accept standard OpenAI function-tool definitions through the
`tools` field and SHALL parse provider `tool_calls` into the normalized
`tool_calls` list so the caller can dispatch and re-inject tool results into
subsequent messages.

#### Scenario: Tool call requested by model

- **WHEN** a call is made with standard tool definitions and the model
  responds with one or more tool calls
- **THEN** the returned structure lists those tool calls with their IDs,
  function names, and JSON argument strings, and the caller can feed the
  tool result back into a follow-up message

### Requirement: Reasoning content is isolated from multi-turn history

The client SHALL capture textual reasoning metadata when an upstream service
returns it, including compatibility fields such as `reasoning_content`, in
the normalized `reasoning` field. A provider that exposes only reasoning-token
usage MAY leave textual `reasoning` empty. The client MUST NOT echo any
reasoning text back into assistant messages in subsequent multi-turn history;
only the model's content and, when applicable, its tool calls SHALL become
the assistant-side history entry.

#### Scenario: Follow-up after a reasoning reply

- **WHEN** a model produces both reasoning metadata and content, and the
  caller builds a follow-up request reusing the conversation history
- **THEN** the assistant history entry contains only content and tool calls,
  never reasoning text, and the follow-up request uses the standard message
  format

#### Scenario: Streaming reasoning reply

- **WHEN** a streaming provider returns reasoning and content deltas
- **THEN** reasoning deltas and content deltas are collected into separate
  normalized fields, and reasoning is not carried into subsequent assistant
  history

### Requirement: Explicit behavior knobs for provider-specific options

Model behavior controls SHALL be exposed as explicit, documented client
parameters. In the standard request path, thinking control SHALL use the
OpenAI-compatible `reasoning_effort` field and SHALL be omitted when the
caller does not set it. The client MUST NOT translate a thinking boolean into
`extra_body.enable_thinking` implicitly or send that Qwen-specific field as
part of a normal call.

#### Scenario: Reasoning effort is sent as the standard field

- **WHEN** a caller sets a reasoning effort value for a model that supports it
- **THEN** the request contains that value in `reasoning_effort` and contains
  no automatic `extra_body.enable_thinking`

#### Scenario: Unspecified reasoning uses provider default

- **WHEN** a caller does not set a reasoning effort value
- **THEN** the request omits `reasoning_effort` and does not invent a
  provider-specific thinking toggle

### Requirement: Per-call observation logs

The client SHALL emit one structured observation entry per completed call that
records at least the model, elapsed time, token usage, and finish reason,
without logging secrets. Usage logging SHALL be a bounded, sanitized summary
and MUST NOT include the raw provider response or API credentials.

#### Scenario: Successful call records an observation

- **WHEN** a call completes and an observation sink is attached
- **THEN** a structured entry containing model, elapsed time, sanitized token
  usage, and finish reason is emitted, and no API key or raw auth material
  appears in the log

### Requirement: Explicit retry and timeout configuration

Retry count and timeout SHALL be explicit, tunable client options rather than
hard-coded values, with sensible defaults when not provided. Explicit zero
values SHALL be honored and MUST NOT be replaced by defaults through
truthiness-based fallback.

#### Scenario: Retry count configured including zero

- **WHEN** a caller or environment sets a retry count to zero, or to a
  positive integer, and an initial attempt fails transiently
- **THEN** the client performs exactly the configured retry policy rather than
  silently substituting the default count
