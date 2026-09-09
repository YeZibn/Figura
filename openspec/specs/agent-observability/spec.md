# agent-observability Specification

## Purpose

Provide a bounded, provider-neutral execution trace for Agent runs so users
can inspect model turns, tool actions, structured outcomes, and generated visual
evidence without changing the messages sent to the model or the default CLI.

## Requirements

### Requirement: Agent execution events are observable

The system SHALL expose an optional trace-event stream for an Agent run. The
stream SHALL identify model turns, provider-returned reasoning when available,
tool calls, tool outcomes, generated visual observations, final answers, and
budget termination in their execution order. Attaching no trace consumer SHALL
preserve the current execution behavior.

#### Scenario: Trace records a successful tool trajectory

- **WHEN** an Agent run requests a tool and then produces a final answer
- **THEN** the trace contains ordered model, tool-call, tool-result, and final
  answer events with the tool name and call identifier

#### Scenario: Trace records generated visual evidence

- **WHEN** a tool result contains one or more valid generated images
- **THEN** the trace records each image's media type, caption, and bounded size
  metadata without exposing its base64 or raw byte payload

#### Scenario: No trace consumer preserves normal execution

- **WHEN** an Agent run is executed without a trace consumer
- **THEN** the model messages, returned answer, and tool behavior remain the
  same as the non-traced path

### Requirement: Trace output is bounded and sanitized

The system SHALL bound displayed or serialized reasoning, tool arguments, tool
results, and other text fields. Trace output MUST NOT contain API credentials,
raw authorization material, or generated image bytes, and SHALL identify
truncated fields when content exceeds the configured limit.

#### Scenario: Oversized tool content is truncated

- **WHEN** a tool argument or result exceeds the trace text limit
- **THEN** the trace includes a bounded prefix and an explicit truncation
  indicator while the Agent receives the original unmodified value

#### Scenario: Sensitive fields are not emitted

- **WHEN** a trace event contains provider configuration or credential-like
  fields
- **THEN** those fields are omitted or redacted before reaching a trace sink

### Requirement: Provider reasoning display is explicit and best effort

The system SHALL keep provider-returned reasoning out of Agent message history.
When an explicit reasoning-display option is enabled, the trace MAY show the
provider-returned reasoning with a clear label; when the provider returns no
reasoning, the trace SHALL remain valid and indicate that it is unavailable.

#### Scenario: Reasoning is displayed only when requested

- **WHEN** the provider returns reasoning and the user enables reasoning display
- **THEN** the trace shows the reasoning as provider-returned diagnostic content
  while the next model request contains no reasoning field in history

#### Scenario: Provider without reasoning remains supported

- **WHEN** the provider returns ordinary content without reasoning
- **THEN** enabling reasoning display does not fail the run and the trace marks
  reasoning as unavailable
