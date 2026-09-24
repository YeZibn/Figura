## MODIFIED Requirements

### Requirement: OpenAI-compatible endpoint configuration layering
The client SHALL resolve an explicit provider selection before resolving
provider-scoped connection and behavior settings. The supported providers are
`openai`, `qwen`, and `deepseek`. OpenAI SHALL use `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, and `OPENAI_MODEL`. Qwen SHALL use `QWEN_API_KEY`,
`QWEN_BASE_URL`, and `QWEN_MODEL`, with the documented DashScope-compatible
endpoint. DeepSeek SHALL use `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and
`DEEPSEEK_MODEL`, defaulting to `https://api.deepseek.com` and the official
model ID `deepseek-flash`. `CHARTAGENT_PROVIDER` SHALL select the default
provider and SHALL continue to default to `openai` for backward compatibility.
Legacy DashScope variables MAY be used only as lower-priority Qwen aliases.
Provider-scoped values MUST NOT leak across providers. Environment loading
MUST remain stable across repository-root and frontend launch directories and
MUST NOT log credentials.

#### Scenario: OpenAI uses the existing relay
- **WHEN** provider `openai` is selected and OpenAI configuration is present
- **THEN** the client uses the configured OpenAI endpoint and credentials without falling back to Qwen or DeepSeek values

#### Scenario: Qwen uses its own configuration
- **WHEN** provider `qwen` is selected and Qwen configuration is present
- **THEN** the client uses Qwen credentials, endpoint, and model, with legacy DashScope aliases considered only when the corresponding Qwen value is absent

#### Scenario: DeepSeek uses its own configuration
- **WHEN** provider `deepseek` is selected and DeepSeek configuration is present
- **THEN** the client uses `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL`, defaulting the endpoint and model to the documented DeepSeek Flash values

#### Scenario: Unknown provider is invalid
- **WHEN** configuration resolves a provider other than `openai`, `qwen`, or `deepseek`
- **THEN** client construction or readiness returns a bounded invalid configuration result without attempting a provider request

#### Scenario: Missing selected-provider credentials are explicit
- **WHEN** the selected provider has no usable API key or model
- **THEN** readiness reports missing or invalid configuration for that provider and the client does not silently switch providers

#### Scenario: Explicit parameters take precedence over environment variables
- **WHEN** a caller supplies an explicit endpoint and API key while the corresponding environment variables are also set
- **THEN** the client uses the explicit values and issues calls against the explicit endpoint and credential

#### Scenario: Canonical provider environment variables are preferred
- **WHEN** a provider is selected and both its canonical variables and a legacy alias are available
- **THEN** the client uses the canonical provider-scoped variables

#### Scenario: Process environment takes precedence over the runtime environment file
- **WHEN** a runtime environment file contains provider settings and the same setting is already present in the process environment
- **THEN** the process environment value wins and the file value is not used for that key

#### Scenario: Legacy variables remain a Qwen migration fallback
- **WHEN** provider `qwen` is selected, no canonical Qwen variable is set, but the corresponding DashScope variable is present
- **THEN** the client derives that setting from the legacy variable and can construct the configured Qwen call target

#### Scenario: Runtime configuration is stable across launch directories
- **WHEN** the Gateway is launched from the repository root or the `frontend` directory with the documented runtime configuration contract
- **THEN** the client resolves the same provider key, endpoint, and model values without requiring a duplicate `frontend/.env` file

#### Scenario: Defaults used when nothing is configured
- **WHEN** no explicit parameter and no relevant environment variable or environment file value is set
- **THEN** the client falls back to the built-in standard OpenAI endpoint and default timeout/retry values, and reports missing credentials when an authenticated client is constructed

### Requirement: OpenAI Chat Completions request contract
Every client invocation SHALL use the common Chat Completions contract with a
model, `messages`, and explicit `stream`. Standard tools SHALL be sent through
`tools` for all supported providers. OpenAI SHALL preserve the current relay
request behavior. Qwen SHALL receive only parameters supported by its
compatibility contract and SHALL receive `extra_body.enable_thinking` when
Qwen thinking is enabled. DeepSeek SHALL use its OpenAI-compatible endpoint,
the standard `tools` field, and `extra_body.thinking` for its documented
thinking-mode switch. Provider-specific fields MUST NOT be sent to another
provider.

#### Scenario: OpenAI request remains compatible with the relay
- **WHEN** an OpenAI run is made with tools, streaming, or standard reasoning options
- **THEN** the request is sent using the current standard request fields and no Qwen- or DeepSeek-specific body

#### Scenario: Qwen thinking request is constructed
- **WHEN** a Qwen run has thinking enabled
- **THEN** the request includes `extra_body: {"enable_thinking": true}` and retains the common messages, stream, and tools fields

#### Scenario: DeepSeek thinking request is constructed
- **WHEN** a DeepSeek run has thinking enabled
- **THEN** the request includes `extra_body: {"thinking": {"type": "enabled"}}`, the configured reasoning effort when present, and retains the common messages, stream, and tools fields

#### Scenario: DeepSeek non-thinking request is constructed
- **WHEN** a DeepSeek run has thinking disabled
- **THEN** the request does not enable DeepSeek thinking and does not send Qwen-specific thinking fields

#### Scenario: Provider-specific fields are isolated
- **WHEN** any supported provider receives a request
- **THEN** the request contains no provider-specific field belonging to another provider

#### Scenario: Plain standard request is constructed
- **WHEN** a caller sends messages without tools, reasoning, or an output limit
- **THEN** the provider receives `model`, `messages`, and `stream`, with no unrequested provider-specific thinking body

#### Scenario: Standard tools and reasoning are propagated
- **WHEN** a caller supplies tool definitions and a supported reasoning effort
- **THEN** the provider receives the same definitions under `tools` and the provider-compatible reasoning level

#### Scenario: OpenAI streaming requests include usage metadata
- **WHEN** an OpenAI caller makes a streaming invocation
- **THEN** the provider receives `stream_options` with `include_usage` set to true, and the normalized result can expose the final usage object when the provider returns one

### Requirement: Normalized output structure
Every provider invocation SHALL return the existing normalized structure with
`content`, `reasoning`, `tool_calls`, `finish_reason`, `usage`, and `raw`.
Provider-returned `reasoning_content` in non-streaming messages and streaming
deltas SHALL be normalized into `reasoning`; ordinary content and tool calls
SHALL retain their existing semantics.

#### Scenario: Qwen reasoning is normalized
- **WHEN** Qwen returns `reasoning_content` followed by content
- **THEN** the result exposes the two parts separately and preserves the raw provider response or ordered chunks

#### Scenario: DeepSeek reasoning is normalized
- **WHEN** DeepSeek returns `reasoning_content` followed by content or tool calls
- **THEN** the result exposes the two parts separately and preserves the raw provider response or ordered chunks

#### Scenario: DeepSeek tool calls remain dispatchable
- **WHEN** DeepSeek returns one or more standard function tool calls
- **THEN** the result contains their IDs, names, and JSON argument strings in the same normalized list used by the other providers

#### Scenario: Normal plain-text reply
- **WHEN** a provider answers with plain content and no tool calls
- **THEN** the returned structure has `content` populated, `reasoning` empty, `tool_calls` empty, and `finish_reason`/`usage` reflecting the response

#### Scenario: Standard response without textual reasoning
- **WHEN** a provider returns ordinary content and usage metadata but no textual reasoning field
- **THEN** `reasoning` is an empty string, usage remains available, and no missing-field exception occurs

#### Scenario: Raw response is always available
- **WHEN** any invocation completes successfully
- **THEN** `raw` contains the untouched response object or ordered stream chunks so the caller can recover fields not normalized by the client

### Requirement: Reasoning content is isolated from multi-turn history
The client SHALL keep provider-returned reasoning out of user-visible
transcripts and ordinary persisted assistant content. Qwen reasoning SHALL
remain excluded from follow-up history. When DeepSeek thinking mode is used
with tools, the runtime SHALL carry the exact provider-returned
`reasoning_content` privately in the required subsequent outbound assistant
message, together with content and tool calls, without exposing it through the
normal answer or trace surface.

#### Scenario: Qwen follow-up excludes reasoning
- **WHEN** a Qwen response contains reasoning and the Agent performs another turn
- **THEN** the follow-up assistant history contains no reasoning text

#### Scenario: DeepSeek tool follow-up preserves required reasoning
- **WHEN** a DeepSeek thinking response contains `reasoning_content` and tool calls
- **THEN** the next tool-capable request includes that exact reasoning field in the provider-required assistant message and the tool remains dispatchable

#### Scenario: DeepSeek final answer does not expose reasoning
- **WHEN** a DeepSeek thinking response completes without another tool call
- **THEN** the user-facing answer contains only normalized content and does not contain provider reasoning unless explicit diagnostic display is enabled

#### Scenario: DeepSeek no-tool follow-up can omit reasoning
- **WHEN** a DeepSeek response is followed by a request without tools and the provider does not require reasoning replay
- **THEN** the runtime may omit reasoning from the ordinary follow-up history while preserving valid message ordering

#### Scenario: Streaming reasoning reply
- **WHEN** a supported provider returns reasoning and content deltas
- **THEN** reasoning deltas and content deltas are collected separately, and only DeepSeek tool-capable follow-ups retain the provider-required reasoning field

### Requirement: Explicit behavior knobs for provider-specific options
Provider behavior controls SHALL be explicit and documented. OpenAI SHALL use
the current `reasoning_effort` behavior. Qwen thinking SHALL be controlled by
the selected-provider configuration and translated only for Qwen into
`extra_body.enable_thinking`. DeepSeek thinking SHALL be controlled by
DeepSeek-scoped configuration and translated only for DeepSeek into
`extra_body.thinking`, with its reasoning effort passed through the documented
standard field when configured. The client MUST NOT send another provider's
thinking fields.

#### Scenario: Qwen thinking can be disabled
- **WHEN** Qwen is selected and thinking is disabled
- **THEN** the request omits or disables `extra_body.enable_thinking` and does not invent DeepSeek thinking fields

#### Scenario: DeepSeek thinking can be disabled
- **WHEN** DeepSeek is selected and thinking is disabled
- **THEN** the request does not enable `extra_body.thinking` and does not send Qwen thinking parameters

#### Scenario: DeepSeek effort is explicit
- **WHEN** DeepSeek is selected with a configured reasoning effort
- **THEN** the request sends the configured effort using the documented `reasoning_effort` field

#### Scenario: OpenAI reasoning remains unchanged
- **WHEN** OpenAI is selected and a reasoning effort is supplied
- **THEN** the request sends the existing OpenAI reasoning field and omits Qwen and DeepSeek thinking parameters

#### Scenario: Unspecified provider reasoning uses provider default
- **WHEN** a caller does not set a provider-specific reasoning control
- **THEN** the client omits unrequested controls and lets that provider's documented default apply
