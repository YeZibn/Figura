## MODIFIED Requirements

### Requirement: User can select the provider for the next run
The desktop workspace SHALL provide a visible provider selector with the
supported choices `OpenAI（中转站）`、`Qwen（DashScope）` and
`DeepSeek（V4.1 Flash）`. The selector SHALL send only the provider identifier
through the Gateway API, preserve the selection for the active session, and
make clear when a changed selection applies to the next run rather than an
active run.

#### Scenario: Provider selector is visible
- **WHEN** the workspace is loaded in Gateway mode
- **THEN** the user can see the current provider and choose OpenAI, Qwen, or DeepSeek using Simplified Chinese labels

#### Scenario: Selection is used on submission
- **WHEN** the user selects DeepSeek and submits a message
- **THEN** the client sends `provider: "deepseek"` with the run request and does not send API keys, endpoints, or arbitrary model parameters

#### Scenario: Selection survives session reload
- **WHEN** the active session is reloaded or revisited
- **THEN** the client restores the session's last effective provider when it is available, or falls back to the Gateway default with a clear state

#### Scenario: Unavailable provider is actionable
- **WHEN** Gateway health reports a provider as unavailable
- **THEN** the selector marks it unavailable or explains the bounded reason and prevents a misleading successful submission
