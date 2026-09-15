# llm-client Specification

## Purpose

Provides a controllable, observable LLM invocation layer over the Alibaba
Cloud compatible-mode endpoint (an OpenAI-compatible deployment). It
normalizes provider responses, isolates reasoning output from multi-turn
history, exposes explicit configuration knobs, emits per-call observation
logs, and loads its environment (key, base_url, default model) from `.env` via
`python-dotenv`.

## Requirements

### Requirement: OpenAI-compatible endpoint configuration layering

The client SHALL resolve an explicit provider selection before resolving
provider-scoped connection and behavior settings. The supported providers are
`openai` and `qwen`. OpenAI SHALL use `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and
`OPENAI_MODEL`, where `OPENAI_BASE_URL` remains the existing OpenAI relay
configured by the deployment. Qwen SHALL use `QWEN_API_KEY`, `QWEN_BASE_URL`,
and `QWEN_MODEL`, with the documented DashScope-compatible endpoint and
`qwen3.8-flash` as the documented example. `CHARTAGENT_PROVIDER` SHALL select
the default provider and SHALL default to `openai` for backward compatibility.
Legacy `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`, and `DASH_MODEL` MAY be used
only as lower-priority Qwen aliases. Provider-scoped values MUST NOT leak across
providers. Environment loading MUST remain stable across repository-root and
frontend launch directories and MUST NOT log credentials.

#### Scenario: OpenAI uses the existing relay

- **WHEN** provider `openai` is selected and OpenAI configuration is present
- **THEN** the client uses the configured `OPENAI_BASE_URL` relay and OpenAI
  credentials, without falling back to Qwen or DashScope values

#### Scenario: Qwen uses its own configuration

- **WHEN** provider `qwen` is selected and Qwen configuration is present
- **THEN** the client uses Qwen credentials, endpoint, and model, with legacy
  DashScope aliases considered only when the corresponding Qwen value is absent

#### Scenario: Unknown provider is invalid

- **WHEN** configuration resolves a provider other than `openai` or `qwen`
- **THEN** client construction or readiness returns a bounded invalid
  configuration result without attempting a provider request

#### Scenario: Missing selected-provider credentials are explicit

- **WHEN** the selected provider has no usable API key or model
- **THEN** readiness reports missing or invalid configuration for that provider
  and the client does not silently switch providers

#### Scenario: Explicit parameters take precedence over environment variables

- **WHEN** a caller supplies an explicit endpoint and API key while the
  corresponding environment variables are also set
- **THEN** the client uses the explicit values and issues calls against the
  explicit endpoint / credential

#### Scenario: Canonical OpenAI environment variables are preferred

- **WHEN** provider `openai` is selected, no explicit endpoint, credential, or
  model is supplied, and both canonical and legacy variables are available
- **THEN** the client uses `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and
  `OPENAI_MODEL`

#### Scenario: Process environment takes precedence over the runtime environment file

- **WHEN** a runtime environment file contains provider settings and the same
  setting is already present in the process environment
- **THEN** the process environment value wins and the file value is not used
  for that key

#### Scenario: Legacy variables remain a Qwen migration fallback

- **WHEN** provider `qwen` is selected, no canonical Qwen variable is set, but
  the corresponding DashScope variable is present in the process environment
  or runtime environment file
- **THEN** the client derives that setting from the legacy variable and can
  construct the configured call target

#### Scenario: Runtime configuration is stable across launch directories

- **WHEN** the Gateway is launched from the repository root or the
  `frontend` directory with the documented runtime configuration contract
- **THEN** the client resolves the same provider key, endpoint, and model values
  without requiring a duplicate `frontend/.env` file

#### Scenario: Defaults used when nothing is configured

- **WHEN** no explicit parameter and no relevant environment variable or
  environment file value is set
- **THEN** the client falls back to the built-in standard OpenAI endpoint and
  default timeout/retry values, and reports missing credentials through the
  existing bounded configuration error when an authenticated client is
  constructed

### Requirement: OpenAI Chat Completions request contract

Every client invocation SHALL use the common Chat Completions contract with a
model, `messages`, and explicit `stream`. Standard tools SHALL be sent through
`tools` for both providers. OpenAI SHALL preserve the current relay request
behavior, including its supported standard parameters. Qwen SHALL receive only
parameters supported by its compatibility contract and SHALL receive
`extra_body.enable_thinking` when Qwen thinking is enabled. Provider-specific
fields MUST NOT be sent to the other provider.

#### Scenario: OpenAI request remains compatible with the relay

- **WHEN** an OpenAI run is made with tools, streaming, or standard reasoning
  options
- **THEN** the request is sent to the configured OpenAI relay using the current
  standard request fields and no Qwen-specific body

#### Scenario: Qwen thinking request is constructed

- **WHEN** a Qwen run has thinking enabled
- **THEN** the request includes `extra_body: {"enable_thinking": true}` and
  retains the common messages, stream, and tools fields

#### Scenario: Provider-specific fields are isolated

- **WHEN** either provider receives a request
- **THEN** the request contains no provider-specific field belonging to the
  other provider

#### Scenario: Plain standard request is constructed

- **WHEN** an OpenAI caller sends messages without tools, reasoning, or an
  output limit
- **THEN** the provider receives `model`, `messages`, and `stream`, with no
  provider-specific thinking body and no deprecated token-limit field

#### Scenario: Standard tools and reasoning are propagated

- **WHEN** an OpenAI caller supplies tool definitions and `reasoning_effort`
- **THEN** the provider receives the same definitions under `tools` and the
  reasoning level under `reasoning_effort`

#### Scenario: OpenAI streaming requests include usage metadata

- **WHEN** an OpenAI caller makes a streaming invocation
- **THEN** the provider receives `stream_options` with `include_usage` set to
  true, and the normalized result can expose the final usage object when the
  provider returns one

### Requirement: Normalized output structure

Every provider invocation SHALL return the existing normalized structure with
`content`, `reasoning`, `tool_calls`, `finish_reason`, `usage`, and `raw`.
Qwen `reasoning_content` in non-streaming messages and streaming deltas SHALL
be normalized into `reasoning`; ordinary content and tool calls SHALL retain
their existing semantics.

#### Scenario: Qwen reasoning is normalized

- **WHEN** Qwen returns `reasoning_content` followed by content
- **THEN** the result exposes the two parts separately and preserves the raw
  provider response or ordered chunks

#### Scenario: Qwen tool calls remain dispatchable

- **WHEN** Qwen returns one or more standard function tool calls
- **THEN** the result contains their IDs, names, and JSON argument strings in
  the same normalized list used by OpenAI

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

The client SHALL continue to exclude normalized reasoning, including Qwen
`reasoning_content`, from assistant history while preserving content and
applicable tool calls for subsequent turns.

#### Scenario: Qwen follow-up excludes reasoning

- **WHEN** a Qwen response contains reasoning and the Agent performs another
  turn
- **THEN** the follow-up assistant history contains no reasoning text

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

Provider behavior controls SHALL be explicit and documented. OpenAI SHALL use
the current `reasoning_effort` behavior. Qwen thinking SHALL be controlled by
the selected-provider configuration, with `QWEN_ENABLE_THINKING` defaulting to
the documented Qwen integration behavior, and SHALL be translated only for
Qwen into `extra_body.enable_thinking`. The client MUST NOT send
`reasoning_effort` to Qwen unless Qwen support for that field is explicitly
validated and configured.

#### Scenario: Qwen thinking can be disabled

- **WHEN** Qwen is selected and thinking is disabled
- **THEN** the request omits `extra_body.enable_thinking` or sends the
  provider-documented false value, and does not invent OpenAI reasoning fields

#### Scenario: OpenAI reasoning remains unchanged

- **WHEN** OpenAI is selected and a reasoning effort is supplied
- **THEN** the request sends the existing OpenAI reasoning field and omits Qwen
  thinking parameters

#### Scenario: Reasoning effort is sent as the standard field

- **WHEN** an OpenAI caller sets a reasoning effort value for a model that
  supports it
- **THEN** the request contains that value in `reasoning_effort` and contains
  no automatic `extra_body.enable_thinking`

#### Scenario: Unspecified OpenAI reasoning uses provider default

- **WHEN** an OpenAI caller does not set a reasoning effort value
- **THEN** the request omits `reasoning_effort` and does not invent a
  provider-specific thinking toggle

### Requirement: Per-call observation logs

The client SHALL include the selected provider in sanitized per-call
observations and trace model boundaries while continuing to omit credentials,
raw endpoints, and raw provider payloads.

#### Scenario: Observation identifies provider safely

- **WHEN** a provider call completes
- **THEN** its observation includes provider and model plus bounded timing,
  usage, and finish data without secret configuration

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
