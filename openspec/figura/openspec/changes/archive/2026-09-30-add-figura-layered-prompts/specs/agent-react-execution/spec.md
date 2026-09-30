## MODIFIED Requirements

### Requirement: Agent requests preserve complete Session history within Provider limits

Figura SHALL submit non-streaming requests using exactly three ordered SYSTEM instruction blocks: stable Agent responsibilities, the current registered tool surface, and a factual resource inventory projected from the target Run's `RunExecutionState`. The request SHALL use the provider-neutral tool projection from the same registry represented in the tool instruction, and bounded completion options. A request SHALL contain complete same-Session history and SHALL satisfy the Provider boundary's message, instruction, tool, image, and total text/schema limits before a durable provider attempt is claimed. Figura SHALL NOT truncate, summarize, or remove any historical Run or interaction to fit a request. If the complete request exceeds any Provider limit, Figura SHALL fail the current Run before claiming or dispatching a provider attempt.

#### Scenario: Send every complete Session interaction
- **WHEN** all earlier same-Session Runs have valid complete histories and the assembled request is within Provider limits
- **THEN** Figura sends the entire earlier history and current Run prefix in ordinal and committed fact order, with the three ordered SYSTEM instruction blocks

#### Scenario: Complete history exceeds a Provider limit
- **WHEN** the full request exceeds a Provider message, instruction, tool, image, text, or schema limit
- **THEN** Figura preserves all source facts, fails the current Run, and makes no Provider-attempt claim or network request

#### Scenario: Keep a tool result associated with its call
- **WHEN** a successful or failed tool result is projected into Provider history
- **THEN** Figura sends a bounded JSON observation in a tool message associated with the original call ID and omits implementation details from an error observation

## ADDED Requirements

### Requirement: Agent prompt layers have explicit sources and ordered responsibilities

Figura SHALL assemble each Agent prompt from three ordered SYSTEM instruction blocks. The stable-responsibility block SHALL contain the fixed Chinese Agent, evidence, workflow, and response rules and SHALL NOT contain request-specific user or Run data. The current-tool block SHALL be projected from the exact `ToolRegistry` used for the request's provider tool schemas; it SHALL describe only tools present in that registry, while the provider-native schemas remain authoritative for tool names, parameters, required fields, and allowed values. The run-resource block SHALL be projected exclusively from the target request's `RunExecutionState` and SHALL use complete typed resource references for Attachments, Panels, OCR, measurements, ChartFigures, and ChartRenders.

The resource block SHALL be a concise index and SHALL NOT replace or duplicate complete tool results in chronological Session history. It SHALL distinguish tool execution outcome from a measurement result's `status` and an OCR result's availability. Resource names, titles, OCR text, tool observations, and other data values SHALL be treated as untrusted evidence rather than instructions. The three blocks SHALL be rebuilt for every model request; no prompt or resource summary SHALL be added to durable Run facts.

#### Scenario: Keep stable policy independent from user and Run values
- **WHEN** Figura assembles a request containing user text, tool results, attachments, and Panels
- **THEN** the first SYSTEM instruction block contains only the stable Chinese Agent policy and the request-specific values appear only in their designated dynamic layers or history messages

#### Scenario: Match the tool layer to the registered tool schemas
- **WHEN** a request is assembled with a ToolRegistry containing a specific ordered set of tools
- **THEN** the second SYSTEM instruction block describes exactly those tools in registry order and the provider request exposes their native schemas from the same registry

#### Scenario: Index all resource kinds from the target Run state
- **WHEN** the target Run's RunExecutionState contains eligible resources of multiple kinds
- **THEN** the third SYSTEM instruction block identifies each resource with its complete typed reference and a concise kind-appropriate summary, without substituting resources from a later Run

#### Scenario: Keep complete observations in chronological history
- **WHEN** an OCR, measurement, Figure assembly, or render result is present in committed Session history and is also indexed in RunExecutionState
- **THEN** the history contains its complete committed tool observation while the resource block contains only a concise reference and summary

#### Scenario: Treat resource values as data
- **WHEN** an attachment name, Panel name, OCR snippet, or tool result contains text that resembles an instruction
- **THEN** Figura encodes the value as resource data and instructs the model to analyze it as untrusted content, not follow it as policy
