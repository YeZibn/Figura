## MODIFIED Requirements

### Requirement: Provider reasoning display is explicit and best effort
The system SHALL keep provider-returned reasoning out of user-visible Agent
message history and ordinary transcript output. When an explicit
reasoning-display option is enabled, the trace MAY show provider-returned
reasoning with a clear label; when the provider returns no reasoning, the trace
SHALL remain valid and indicate that it is unavailable. For DeepSeek thinking
mode with tool calls, the runtime MAY retain the exact `reasoning_content`
needed for the next provider request in private in-memory or checkpoint
context, but MUST NOT expose it as ordinary assistant content or emit it as
unbounded trace payload.

#### Scenario: Reasoning is displayed only when requested
- **WHEN** a provider returns reasoning and the user enables reasoning display
- **THEN** the trace shows the reasoning as provider-returned diagnostic content while the normal assistant answer remains content-only

#### Scenario: DeepSeek tool reasoning remains private
- **WHEN** DeepSeek returns reasoning_content together with a tool call
- **THEN** the next DeepSeek request can receive the required reasoning field, but the user transcript and normal run answer do not contain that reasoning

#### Scenario: Provider without reasoning remains supported
- **WHEN** a provider returns ordinary content without reasoning
- **THEN** enabling reasoning display does not fail the run and the trace marks reasoning as unavailable
