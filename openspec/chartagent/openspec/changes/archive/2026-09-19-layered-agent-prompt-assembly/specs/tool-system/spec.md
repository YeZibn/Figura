## MODIFIED Requirements

### Requirement: Declarative tool definition

The system SHALL let a tool be declared as metadata plus a callable: a stable
English name, a model-facing description, a JSON-Schema description of
accepted parameters, and a Python callable that executes the tool. A tool MAY
also carry a human-readable display name and a stable group identifier for
user interfaces and execution traces. The model-facing description SHALL be
concise, written in Simplified Chinese for natural-language guidance, and
explain the tool's purpose, applicable input or situation, when it should not
be used, returned data or visual evidence, and material limitations. Technical
identifiers, parameter names, enum values, and protocol fields SHALL retain
their stable English spelling. The metadata SHALL be independent of the
callable so the same tool can be described to an LLM or mapped to an external
protocol without touching the callable.

#### Scenario: Register a tool carrying core and display metadata

- **WHEN** a tool is created with a name, description, parameters schema, callable, and optional display metadata
- **THEN** the definition retains the stable name, description, parameters, callable, display name, and group without executing or introspecting the callable

#### Scenario: Existing tool construction remains compatible

- **WHEN** a tool is created using only the existing name, description, parameters, and callable fields
- **THEN** it remains valid with deterministic defaults for omitted optional metadata
- **AND** its existing function-calling name and callable behavior do not change

#### Scenario: Tool description gives actionable Chinese selection guidance

- **WHEN** a registered tool is exposed to a model
- **THEN** the description identifies in Chinese what the tool does, when its input is appropriate, when it should not be used, what evidence or data it returns, and any material limitation
- **AND** stable English identifiers remain recognizable to the model and external protocol adapters

#### Scenario: Tool metadata stays decoupled from the callable

- **WHEN** a tool is read back for LLM tool-definition or external mapping
- **THEN** the name, description and parameters schema are available without executing or introspecting the callable
