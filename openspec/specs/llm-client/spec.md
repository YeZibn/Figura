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

The client SHALL resolve connection and behavior configuration with the
precedence: explicit parameters > environment variables (loaded from `.env`
via `python-dotenv`) > default values.
The client MUST support `DASHSCOPE_API_KEY` as the environment-variable
credential source, MUST use `DASHSCOPE_BASE_URL` (falling back to a built-in
default Alibaba compatible-mode endpoint) as `base_url`, and MUST allow an
explicit `base_url` to override any default endpoint. A default model
(`DASH_MODEL`) SHALL be configurable and usable when a call omits `model`.

#### Scenario: Explicit parameters take precedence over environment variables

- **WHEN** a caller supplies an explicit `base_url` and API key while the
  corresponding environment variables are also set
- **THEN** the client uses the explicit values and issues calls against the
  explicit endpoint / credential

#### Scenario: Environment variables used when no explicit parameter is given

- **WHEN** a caller omits the endpoint and credential but `base_url` and
  `DASHSCOPE_API_KEY` are set in the environment
- **THEN** the client derives endpoint and credential from the environment and
  completes the call

#### Scenario: Defaults used when nothing is configured

- **WHEN** no explicit parameter and no relevant environment variable is set
- **THEN** the client falls back to built-in default values and is still able
  to construct a configured call target

### Requirement: Normalized output structure

Every chat/tool invocation SHALL return a single normalized structure exposing
`content`, `reasoning`, `tool_calls` (a list), `finish_reason`, `usage`, and
`raw`. `raw` MUST preserve the original provider response as a fallback so no
provider-specific detail is ever lost. When a field is not applicable (for
example no reasoning produced, or no tool calls made), the corresponding field
MUST be present with a stable empty/absent value rather than being omitted
ambiguously.

#### Scenario: Normal plain-text reply

- **WHEN** the model answers with plain content and no tool calls
- **THEN** the returned structure has `content` populated, `reasoning` empty,
  `tool_calls` empty, and `finish_reason`/`usage` reflecting the response

#### Scenario: Raw response is always available

- **WHEN** any invocation completes successfully
- **THEN** `raw` contains the original provider response object so the caller
  can recover any untouched field

### Requirement: Tool definition calls with correct tool_calls propagation

The client SHALL accept user-provided tool definitions for a call and SHALL
parse provider `tool_calls` into the normalized `tool_calls` list so the caller
can dispatch and re-inject tool results back into subsequent messages.

#### Scenario: Tool call requested by model

- **WHEN** a call is made with tool definitions and the model responds with one
  or more tool calls
- **THEN** the returned structure lists those tool calls in `tool_calls` with
  their name/arguments, and the caller can feed the tool result back into a
  follow-up message

### Requirement: Reasoning content is isolated from multi-turn history

For providers exposing non-standard reasoning output (for example
`reasoning_content` on deep-thinking models), the client SHALL capture the
reasoning text into the normalized `reasoning` field and MUST NOT echo reasoning
content back into the assistant messages of any subsequent multi-turn history.
Only the model's content SHALL become the assistant-side history entry.

#### Scenario: Follow-up after a deep-thinking reply

- **WHEN** a deep-thinking model produces both reasoning and content, and the
  caller builds a follow-up request reusing the conversation history
- **THEN** the assistant history entry contains only the content, never the
  reasoning, and the follow-up call does not fail with a provider-side error

#### Scenario: Streaming deep-thinking reply

- **WHEN** streaming a deep-thinking model response
- **THEN** reasoning deltas and content deltas are collected into separate
  fields of the final normalized result, and the reasoning is not carried into
  subsequent assistant history

### Requirement: Explicit behavior knobs for provider-specific options

Provider-specific behavior switches (such as a thinking-mode toggle that
compiles to a provider extension field like `enable_thinking`) SHALL be exposed
as explicit, documented client parameters rather than implicit magic.

#### Scenario: Thinking toggle honored

- **WHEN** a caller sets the thinking switch to disabled/enabled for a
  deep-thinking model
- **THEN** the client translates that switch into the provider's extension
  field and the response reflects the toggled behavior

### Requirement: Per-call observation logs

The client SHALL emit one structured observation entry per completed call that
records at least the model, elapsed time, token usage, and finish reason,
without logging secrets.

#### Scenario: Successful call records an observation

- **WHEN** a call completes and an observation sink is attached
- **THEN** a structured entry containing model, elapsed time, usage, and finish
  reason is emitted, and no API key / raw full auth material appears in the log

### Requirement: Explicit retry and timeout configuration

Retry count and timeout SHALL be explicit, tunable client options rather than
hard-coded values, with sensible defaults when not provided.

#### Scenario: Retry count configured

- **WHEN** a caller provides an explicit retry count and an initial attempt fails
  transiently
- **THEN** the client retries up to the configured count before surfacing a
  final error