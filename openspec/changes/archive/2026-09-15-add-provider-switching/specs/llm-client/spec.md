## MODIFIED Requirements

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

### Requirement: OpenAI-compatible Chat Completions request contract

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

### Requirement: Reasoning content is isolated from multi-turn history

The client SHALL continue to exclude normalized reasoning, including Qwen
`reasoning_content`, from assistant history while preserving content and
applicable tool calls for subsequent turns.

#### Scenario: Qwen follow-up excludes reasoning

- **WHEN** a Qwen response contains reasoning and the Agent performs another
  turn
- **THEN** the follow-up assistant history contains no reasoning text

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

### Requirement: Per-call observation logs

The client SHALL include the selected provider in sanitized per-call
observations and trace model boundaries while continuing to omit credentials,
raw endpoints, and raw provider payloads.

#### Scenario: Observation identifies provider safely

- **WHEN** a provider call completes
- **THEN** its observation includes provider and model plus bounded timing,
  usage, and finish data without secret configuration

### Requirement: Explicit retry and timeout configuration

Retry and timeout settings SHALL be resolved from the selected provider's
configuration, while explicit constructor or call overrides and zero values
retain the existing precedence semantics.

#### Scenario: Provider-specific timeout is honored

- **WHEN** Qwen has a configured timeout and retry count
- **THEN** the Qwen SDK client receives those values and OpenAI settings are not
  substituted
